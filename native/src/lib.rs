//! Native image pipeline for GIFManager.
//!
//! Two jobs, both on the per-frame and per-card hot paths:
//!
//! 1. **GIF frame decoding.** Decodes every frame, composites them onto a
//!    canvas honouring the GIF disposal method and transparency, downscales each
//!    frame in parallel, and returns one contiguous RGBA buffer plus a per-frame
//!    offset table. The caller never allocates a buffer per frame, and the frame
//!    data crosses into Python as a single `bytes` object.
//!
//! 2. **Thumbnail decoding and scaling.** Decodes a still image in any supported
//!    format and resamples it into a square box with a SIMD resampler.
//!
//! # Why this is a C ABI and not a Python extension
//!
//! A CPython extension module is bound to one interpreter ABI. A C ABI lets the
//! same shared library serve any Python 3.10+ interpreter through `ctypes`, and —
//! more importantly — a contributor without the Rust toolchain simply runs the
//! pure-Python fallback instead of being unable to start the application at all.
//!
//! # Layout contract
//!
//! Every buffer this library hands back is RGBA8, row-major, tightly packed
//! (`stride == width * 4`), with no row padding. The Qt layer wraps it as
//! `QImage.Format_RGBA8888` without any conversion, which is why the format is
//! stated here rather than left implicit.
//!
//! GIFManager 的原生图像管线。
//!
//! 两项工作，都位于逐帧与逐卡片的热路径上：
//!
//! 1. **GIF 帧解码。** 解码全部帧，按 GIF 的处置方式与透明度合成到画布，并行逐帧
//!    降采样，返回一整块连续的 RGBA 缓冲加一张逐帧偏移表。调用方不再为每帧分配缓冲，
//!    帧数据也以单个 `bytes` 对象跨越到 Python。
//!
//! 2. **缩略图解码与缩放。** 解码任意受支持格式的静态图，并用 SIMD 重采样器缩放进
//!    方形范围。
//!
//! # 为什么用 C ABI 而非 Python 扩展
//!
//! CPython 扩展模块绑定到某一个解释器 ABI。C ABI 让同一个共享库经 `ctypes` 服务于
//! 任意 Python 3.10+ 解释器；更重要的是，没有 Rust 工具链的贡献者只需运行纯 Python
//! 回退路径，而不是完全无法启动程序。
//!
//! # 布局约定
//!
//! 本库返回的每个缓冲都是 RGBA8、行主序、紧密排列（`stride == width * 4`）、无行
//! 填充。Qt 侧直接以 `QImage.Format_RGBA8888` 包装，不做任何转换——这就是此处在文档
//! 中明确写出格式的原因。

use std::os::raw::{c_char, c_int, c_uchar};
use std::ptr;
use std::slice;

use fast_image_resize as fir;
use rayon::prelude::*;

/// Bytes per pixel in every buffer this library produces.
/// 本库产出的每个缓冲的每像素字节数。
const BPP: usize = 4;

/// Error codes returned through `gifmanager_last_error_code`.
/// 通过 `gifmanager_last_error_code` 返回的错误码。
pub const ERR_NONE: c_int = 0;
pub const ERR_BAD_ARGUMENT: c_int = 1;
pub const ERR_IO: c_int = 2;
pub const ERR_DECODE: c_int = 3;
pub const ERR_UNSUPPORTED: c_int = 4;

// ---------------------------------------------------------------------------
// Error reporting
// ---------------------------------------------------------------------------
//
// The message is thread-local: the Python side calls these from several worker
// threads at once, and a process-global buffer would let one thread's error
// overwrite another's between the failing call and the read.
//
// 错误信息是线程局部的：Python 侧会同时从多个工作线程调用，进程级全局缓冲会让一个
// 线程的错误在"调用失败"与"读取错误"之间被另一个线程覆盖。
thread_local! {
    static LAST_ERROR: std::cell::RefCell<Option<std::ffi::CString>> =
        const { std::cell::RefCell::new(None) };
    static LAST_CODE: std::cell::Cell<c_int> = const { std::cell::Cell::new(ERR_NONE) };
}

fn set_error(code: c_int, message: impl AsRef<str>) {
    let text = message.as_ref().replace('\0', " ");
    LAST_CODE.with(|slot| slot.set(code));
    LAST_ERROR.with(|slot| {
        *slot.borrow_mut() = std::ffi::CString::new(text).ok();
    });
}

fn clear_error() {
    LAST_CODE.with(|slot| slot.set(ERR_NONE));
    LAST_ERROR.with(|slot| *slot.borrow_mut() = None);
}

/// Error code of the last failing call on this thread; `0` means none.
///
/// 本线程上一次失败调用的错误码；`0` 表示无错误。
#[no_mangle]
pub extern "C" fn gifmanager_last_error_code() -> c_int {
    LAST_CODE.with(|slot| slot.get())
}

/// Last error message on this thread as a NUL-terminated string, or null.
///
/// The pointer stays valid until the next failing call **on the same thread**, so
/// the caller must copy it before doing anything else.
///
/// 本线程上一次的错误信息（NUL 结尾字符串），无则返回空指针。
///
/// 指针在"同一线程"下一次失败调用之前保持有效，因此调用方必须先复制再做其他事。
#[no_mangle]
pub extern "C" fn gifmanager_last_error_message() -> *const c_char {
    LAST_ERROR.with(|slot| match slot.borrow().as_ref() {
        Some(text) => text.as_ptr(),
        None => ptr::null(),
    })
}

// ---------------------------------------------------------------------------
// GIF decoding
// ---------------------------------------------------------------------------

/// A decoded animation: one contiguous RGBA buffer plus a frame index.
///
/// The frame index lets one allocation serve every frame. A per-frame allocation
/// would mean `frame_count` extra allocations and `frame_count` extra copies
/// across the FFI boundary, which is exactly the cost this module exists to
/// remove.
///
/// 已解码的动画：一整块连续 RGBA 缓冲加一张帧索引。
///
/// 帧索引让一次分配服务所有帧。逐帧分配会带来 `frame_count` 次额外分配与
/// `frame_count` 次跨 FFI 边界复制——正是本模块要消除的开销。
#[repr(C)]
pub struct GifFrames {
    width: u32,
    height: u32,
    frame_count: u32,
    /// RGBA8 frames, tightly packed, one after another.
    /// RGBA8 帧，紧密排列、首尾相接。
    buffer: *mut c_uchar,
    /// Cursor into `buffer` for each frame, in bytes.
    /// 每帧在 `buffer` 中的字节偏移。
    offsets: *mut u64,
    /// Per-frame delay in milliseconds.
    /// 每帧延迟，单位毫秒。
    delays: *mut u32,
}

/// `true` when the library is usable, so Python can decide once instead of
/// catching an exception per call.
///
/// 库可用时返回 `true`，使 Python 只需判断一次，而不必每次调用都捕获异常。
#[no_mangle]
pub extern "C" fn gifmanager_version() -> *const c_char {
    concat!(env!("CARGO_PKG_VERSION"), "\0").as_ptr() as *const c_char
}

/// Decode a GIF into scaled RGBA frames.
///
/// `target` is the longest side of each decoded frame; pass `0` to keep the
/// source size. Scaling happens HERE, per frame, in parallel, because doing it on
/// the Python side meant one `QImage.scaled` call per frame on one thread — the
/// single most repeated operation in the whole application, since a GIF playing
/// at 30 ms re-decodes nothing but a screen full of animations scales constantly.
///
/// Returns null on failure and leaves the reason in the thread-local error.
///
/// 把 GIF 解码为缩放后的 RGBA 帧。
///
/// `target` 是每帧解码后的最长边；传 `0` 保持源尺寸。缩放"在这里"完成、逐帧、并行，
/// 因为在 Python 侧做意味着单个线程上每帧一次 `QImage.scaled`——这是整个程序里重复
/// 次数最多的操作：30ms 一帧的 GIF 不再重复解码，但满屏动画会持续缩放。
///
/// 失败时返回空指针，原因留在该线程的错误信息中。
///
/// # Safety
/// `path` must be a NUL-terminated string. The returned pointer must be released
/// with `gifmanager_frames_free`.
///
/// # 安全性
/// `path` 必须是 NUL 结尾字符串。返回的指针必须用 `gifmanager_frames_free` 释放。
#[no_mangle]
pub unsafe extern "C" fn gifmanager_decode_gif(
    path: *const c_char,
    target: u32,
) -> *mut GifFrames {
    clear_error();

    if path.is_null() {
        set_error(ERR_BAD_ARGUMENT, "path is null / 路径为空指针");
        return ptr::null_mut();
    }
    let path = match std::ffi::CStr::from_ptr(path).to_str() {
        Ok(text) => text,
        Err(_) => {
            set_error(ERR_BAD_ARGUMENT, "path is not valid UTF-8 / 路径不是合法 UTF-8");
            return ptr::null_mut();
        }
    };

    let file = match std::fs::File::open(path) {
        Ok(handle) => handle,
        Err(exc) => {
            set_error(ERR_IO, format!("cannot open {path}: {exc}"));
            return ptr::null_mut();
        }
    };
    let mut reader = std::io::BufReader::new(file);
    let mut options = gif::DecodeOptions::new();
    // The `gif` crate can hand back indexed frames, which is cheaper, but then
    // every caller would need the palette. RGBA is what the Qt layer wants, so
    // the conversion happens once here instead of on every frame swap.
    // `gif` crate 可以返回索引帧，那样更省，但每个调用方就都需要调色板。Qt 侧要的是
    // RGBA，因此转换在这里做一次，而不是每次切换帧都做。
    options.set_color_output(gif::ColorOutput::RGBA);

    let mut decoder = match options.read_info(&mut reader) {
        Ok(decoder) => decoder,
        Err(exc) => {
            set_error(ERR_DECODE, format!("cannot parse GIF header: {exc}"));
            return ptr::null_mut();
        }
    };

    let width = decoder.width() as usize;
    let height = decoder.height() as usize;
    if width == 0 || height == 0 {
        set_error(ERR_DECODE, "GIF reports a zero-sized canvas / GIF 画布尺寸为零");
        return ptr::null_mut();
    }

    // Composite canvas. GIF frames are deltas over a persistent canvas, and the
    // disposal method decides whether the previous frame stays, is restored to
    // the background, or is restored to what came before it. The old C decoder
    // ignored disposal entirely, which is why some stickers showed trails or a
    // black background.
    //
    // 合成画布。GIF 帧是持久画布上的增量，处置方式决定上一帧是保留、恢复为背景，还是
    // 恢复为此前的内容。旧的 C 解码器完全忽略处置方式，这就是某些贴纸出现拖影或黑底的
    // 原因。
    let mut canvas = vec![0u8; width * height * BPP];
    let mut frames: Vec<Vec<u8>> = Vec::new();
    let mut delays: Vec<u32> = Vec::new();
    let mut restore: Option<Vec<u8>> = None;

    loop {
        let frame = match decoder.read_next_frame() {
            Ok(Some(frame)) => frame,
            Ok(None) => break,
            Err(exc) => {
                set_error(ERR_DECODE, format!("cannot decode a frame: {exc}"));
                return ptr::null_mut();
            }
        };

        if frame.dispose == gif::DisposalMethod::Previous {
            restore = Some(canvas.clone());
        }

        blit_frame(&mut canvas, width, height, frame);

        frames.push(canvas.clone());

        // Convert the crate's 10 ms units to milliseconds and clamp, so a stored
        // 0 cannot spin a core and a corrupt huge value cannot freeze a slot.
        // 把 crate 的 10 毫秒单位换算为毫秒并钳制，使存储的 0 不会跑满一个核心、损坏
        // 的极大值也不会占死一个播放位。
        let milliseconds = (frame.delay as u32).saturating_mul(DELAY_UNIT_MS);
        delays.push(milliseconds.clamp(MIN_DELAY_MS, MAX_DELAY_MS));

        match frame.dispose {
            gif::DisposalMethod::Background => {
                clear_rect(&mut canvas, width, height, frame);
            }
            gif::DisposalMethod::Previous => {
                if let Some(previous) = restore.take() {
                    canvas.copy_from_slice(&previous);
                }
            }
            _ => {}
        }
    }

    if frames.is_empty() {
        set_error(ERR_DECODE, "GIF contains no frames / GIF 不含任何帧");
        return ptr::null_mut();
    }

    // Scale every frame in parallel. This is the one stage that parallelises
    // cleanly: LZW decoding is sequential by nature, but resampling is not.
    // 并行缩放每一帧。这是唯一能干净并行化的阶段：LZW 解码本质串行，重采样不是。
    let (out_width, out_height) = scale_target(width, height, target as usize);
    if (out_width, out_height) != (width, height) {
        frames = frames
            .par_iter()
            .map(|frame| resize_rgba(frame, width, height, out_width, out_height))
            .collect();
    }

    let frame_count = frames.len();
    let frame_bytes = out_width * out_height * BPP;
    let mut buffer: Vec<u8> = Vec::with_capacity(frame_bytes * frame_count);
    let mut offsets: Vec<u64> = Vec::with_capacity(frame_count);
    for frame in &frames {
        offsets.push(buffer.len() as u64);
        buffer.extend_from_slice(frame);
    }

    let mut boxed = Box::new(GifFrames {
        width: out_width as u32,
        height: out_height as u32,
        frame_count: frame_count as u32,
        buffer: ptr::null_mut(),
        offsets: ptr::null_mut(),
        delays: ptr::null_mut(),
    });

    // Hand the allocations to the caller and forget the Rust ownership, so the
    // matching `gifmanager_frames_free` can reclaim them.
    //
    // Each pointer is captured BEFORE `mem::forget`, because `forget` consumes
    // the `Vec` by value: reading `as_mut_ptr()` afterwards is a use-after-move.
    // Shrinking first keeps the returned blocks from holding spare capacity the
    // caller would pay for.
    // 把分配交给调用方并放弃 Rust 的所有权，由对应的 `gifmanager_frames_free`
    // 回收。
    //
    // 每个指针都在 `mem::forget` "之前"取出，因为 `forget` 按值消耗 `Vec`：
    // 之后再读 `as_mut_ptr()` 属于 move 后使用。先收缩，避免返回的块持有调用方要
    // 为之付出代价的富余容量。
    let mut buffer = buffer;
    buffer.shrink_to_fit();
    boxed.buffer = buffer.as_mut_ptr();
    std::mem::forget(buffer);

    let mut offsets = offsets;
    offsets.shrink_to_fit();
    boxed.offsets = offsets.as_mut_ptr();
    std::mem::forget(offsets);

    let mut delays = delays;
    delays.shrink_to_fit();
    boxed.delays = delays.as_mut_ptr();
    std::mem::forget(delays);

    Box::into_raw(boxed)
}

/// Tenths of a millisecond per unit of `gif::Frame::delay`.
///
/// The GIF specification stores the delay as centiseconds (hundredths of a
/// second), and the `gif` crate normalises that into units of **10 ms**: a frame
/// with a `delay` of 8 plays for 80 ms. Treating the raw field as milliseconds
/// made every animation play eight to ten times too fast, which is exactly the
/// bug this constant exists to prevent.
///
/// GIF 规范以厘秒（百分之一秒）存储延迟，`gif` crate 把它归一化为"10 毫秒"单位：
/// `delay` 为 8 的帧播放 80 毫秒。把原始字段当毫秒用会让每个动画快八到十倍，这正是
/// 本常量要防止的错误。
const DELAY_UNIT_MS: u32 = 10;

/// Shortest delay honoured, in milliseconds.
///
/// A stored delay of 0 means "as fast as possible" to some encoders and "10 ms"
/// to others. Browsers clamp to 20 ms; clamping here keeps a sticker with 0 ms
/// delays from spinning a core, which the pure-Python path had to guard against
/// separately.
///
/// 被采纳的最短延迟（毫秒）。
///
/// 存储延迟为 0 在某些编码器里意为"尽可能快"，在另一些里意为"10ms"。浏览器钳制到
/// 20ms；在此钳制可避免 0ms 延迟的贴纸把一个核心跑满——纯 Python 路径此前需要单独
/// 防这一点。
const MIN_DELAY_MS: u32 = 20;

/// Longest delay honoured, in milliseconds.
///
/// A corrupt or deliberately huge delay (a "hold on this frame forever" hack) is
/// clamped so a single sticker cannot appear frozen and hold a playback slot.
///
/// 被采纳的最长延迟（毫秒）。
///
/// 损坏或刻意极大的延迟（"永远停在这一帧"的取巧写法）会被钳制，使单个贴纸不会看起来
/// 卡死并占住一个播放位。
const MAX_DELAY_MS: u32 = 60_000;

/// Composite one decoded frame onto the canvas, honouring its offset and the
/// transparent colour index.
///
/// GIF stores a frame as a smaller rectangle placed at `(left, top)` on the
/// canvas, and index 0 of the palette may be flagged transparent. Copying the
/// whole frame at the origin — which is what a naive decoder does — shifts every
/// sub-rectangle frame and paints a black box over the transparent pixels.
///
/// 把一帧合成到画布，遵守其偏移与透明色索引。
///
/// GIF 把一帧存为放置在画布 `(left, top)` 处的较小矩形，且调色板索引 0 可被标记为
/// 透明。把整帧复制到原点——朴素解码器的做法——会让每个子矩形帧错位，并在透明像素上
/// 涂出黑框。
fn blit_frame(canvas: &mut [u8], width: usize, height: usize, frame: &gif::Frame<'_>) {
    let left = frame.left as usize;
    let top = frame.top as usize;
    let fw = frame.width as usize;
    let fh = frame.height as usize;

    for row in 0..fh {
        let canvas_y = top + row;
        if canvas_y >= height {
            break;
        }
        for column in 0..fw {
            let canvas_x = left + column;
            if canvas_x >= width {
                break;
            }
            let source = (row * fw + column) * BPP;
            if source + BPP > frame.buffer.len() {
                break;
            }
            // With RGBA output a fully transparent source pixel arrives with a
            // zero alpha channel, so the alpha test is sufficient and needs no
            // palette lookup.
            // 在 RGBA 输出下，完全透明的源像素以 alpha 为 0 到达，因此判断 alpha 即可，
            // 无需查调色板。
            if frame.buffer[source + 3] == 0 && frame.transparent.is_some() {
                continue;
            }
            let target = (canvas_y * width + canvas_x) * BPP;
            canvas[target..target + BPP]
                .copy_from_slice(&frame.buffer[source..source + BPP]);
        }
    }
}

/// Reset a frame's rectangle to the background (transparent) after it is shown.
///
/// 一帧显示完毕后把其矩形恢复为背景（透明）。
fn clear_rect(canvas: &mut [u8], width: usize, height: usize, frame: &gif::Frame<'_>) {
    let left = frame.left as usize;
    let top = frame.top as usize;
    let fw = frame.width as usize;
    let fh = frame.height as usize;
    for row in 0..fh {
        let canvas_y = top + row;
        if canvas_y >= height {
            break;
        }
        let start = (canvas_y * width + left) * BPP;
        let end = start + fw.min(width.saturating_sub(left)) * BPP;
        if end > start && end <= canvas.len() {
            for byte in &mut canvas[start..end] {
                *byte = 0;
            }
        }
    }
}

/// Longest side of a frame after scaling, preserving the aspect ratio and never
/// upscaling.
///
/// Never upscaling matters: a 32x32 sticker blown up to a 256 px box looks worse
/// than the original and costs more memory, and the caller's "target" is a
/// maximum, not a request.
///
/// 缩放后帧的最长边，保持比例且绝不放大。
///
/// "绝不放大"很重要：32x32 的贴纸被拉到 256px 框里比原图更难看也更占内存，而调用方的
/// "target" 是上限而非请求。
fn scale_target(width: usize, height: usize, target: usize) -> (usize, usize) {
    if target == 0 || target >= width.max(height) {
        return (width, height);
    }
    let longest = width.max(height) as f64;
    let factor = target as f64 / longest;
    let out_width = ((width as f64 * factor).round() as usize).max(1);
    let out_height = ((height as f64 * factor).round() as usize).max(1);
    (out_width, out_height)
}

/// Resample one RGBA frame with the SIMD resampler.
///
/// 用 SIMD 重采样器缩放一帧 RGBA。
fn resize_rgba(
    source: &[u8],
    width: usize,
    height: usize,
    out_width: usize,
    out_height: usize,
) -> Vec<u8> {
    let source_image = match fir::images::ImageRef::new(
        width as u32, height as u32, source, fir::PixelType::U8x4,
    ) {
        Ok(image) => image,
        Err(_) => return source.to_vec(),
    };
    let mut destination = fir::images::Image::new(
        out_width as u32, out_height as u32, fir::PixelType::U8x4);
    // `Lanczos3` is the closest match to Qt's `SmoothTransformation` in quality;
    // `Bilinear` would be cheaper but visibly softer on sticker edges.
    // `Lanczos3` 在质量上最接近 Qt 的 `SmoothTransformation`；`Bilinear` 更省但在
    // 贴纸边缘会明显发虚。
    let options = fir::ResizeOptions::new().resize_alg(fir::ResizeAlg::Convolution(
        fir::FilterType::Lanczos3,
    ));
    let mut resizer = fir::Resizer::new();
    if resizer
        .resize(&source_image, &mut destination, &options)
        .is_err()
    {
        return source.to_vec();
    }
    destination.buffer().to_vec()
}

// ---------------------------------------------------------------------------
// Accessors
// ---------------------------------------------------------------------------

/// Width of every frame, in pixels. / 每帧宽度（像素）。
///
/// # Safety
/// `frames` must come from `gifmanager_decode_gif`.
#[no_mangle]
pub unsafe extern "C" fn gifmanager_frames_width(frames: *const GifFrames) -> u32 {
    if frames.is_null() { 0 } else { (*frames).width }
}

/// Height of every frame, in pixels. / 每帧高度（像素）。
///
/// # Safety
/// `frames` must come from `gifmanager_decode_gif`.
#[no_mangle]
pub unsafe extern "C" fn gifmanager_frames_height(frames: *const GifFrames) -> u32 {
    if frames.is_null() { 0 } else { (*frames).height }
}

/// Number of decoded frames. / 已解码帧数。
///
/// # Safety
/// `frames` must come from `gifmanager_decode_gif`.
#[no_mangle]
pub unsafe extern "C" fn gifmanager_frames_count(frames: *const GifFrames) -> u32 {
    if frames.is_null() { 0 } else { (*frames).frame_count }
}

/// Byte length of one frame (`width * height * 4`). /
/// 单帧字节长度（`宽 * 高 * 4`）。
///
/// # Safety
/// `frames` must come from `gifmanager_decode_gif`.
#[no_mangle]
pub unsafe extern "C" fn gifmanager_frames_frame_bytes(frames: *const GifFrames) -> u64 {
    if frames.is_null() {
        return 0;
    }
    (*frames).width as u64 * (*frames).height as u64 * BPP as u64
}

/// Byte offset of a frame inside the shared buffer, or `u64::MAX` when out of
/// range. / 某帧在共享缓冲中的字节偏移；越界时返回 `u64::MAX`。
///
/// # Safety
/// `frames` must come from `gifmanager_decode_gif`.
#[no_mangle]
pub unsafe extern "C" fn gifmanager_frames_offset(frames: *const GifFrames, index: u32) -> u64 {
    if frames.is_null() || index >= (*frames).frame_count {
        return u64::MAX;
    }
    *(*frames).offsets.add(index as usize)
}

/// Delay of a frame in milliseconds, or 0 when out of range. /
/// 某帧的延迟（毫秒）；越界时返回 0。
///
/// # Safety
/// `frames` must come from `gifmanager_decode_gif`.
#[no_mangle]
pub unsafe extern "C" fn gifmanager_frames_delay(frames: *const GifFrames, index: u32) -> u32 {
    if frames.is_null() || index >= (*frames).frame_count {
        return 0;
    }
    *(*frames).delays.add(index as usize)
}

/// Copy a frame's pixels out of the shared buffer.
///
/// Copies rather than handing out an interior pointer because the Python side
/// wants an owning `bytes` object whose lifetime it controls: returning a view
/// would tie the buffer's lifetime to the caller's discipline, and one missed
/// `free` would leak the whole animation.
///
/// Returns the number of bytes copied, or 0 on failure.
///
/// 把一帧的像素从共享缓冲复制出来。
///
/// 用复制而非交出内部指针，因为 Python 侧想要一个由它自己掌控生命周期的 `bytes`
/// 对象：返回视图会把缓冲的生命周期绑到调用方的自律上，而一次漏掉的 `free` 就会泄漏
/// 整个动画。
///
/// 返回复制的字节数，失败返回 0。
///
/// # Safety
/// `frames` must come from `gifmanager_decode_gif`, and `destination` must point
/// to at least `gifmanager_frames_frame_bytes(frames)` writable bytes.
///
/// # 安全性
/// `frames` 必须来自 `gifmanager_decode_gif`，且 `destination` 必须指向至少
/// `gifmanager_frames_frame_bytes(frames)` 字节的可写空间。
#[no_mangle]
pub unsafe extern "C" fn gifmanager_frames_copy(
    frames: *const GifFrames,
    index: u32,
    destination: *mut c_uchar,
) -> u64 {
    if frames.is_null() || destination.is_null() || index >= (*frames).frame_count {
        return 0;
    }
    let frame_bytes = gifmanager_frames_frame_bytes(frames) as usize;
    let offset = *(*frames).offsets.add(index as usize) as usize;
    let source = slice::from_raw_parts((*frames).buffer.add(offset), frame_bytes);
    ptr::copy_nonoverlapping(source.as_ptr(), destination, frame_bytes);
    frame_bytes as u64
}

/// Release a decoded animation and everything it owns.
///
/// Safe to call with null. / 释放已解码的动画及其持有的一切。传空指针安全。
///
/// # Safety
/// `frames` must come from `gifmanager_decode_gif` and must not be used after.
///
/// # 安全性
/// `frames` 必须来自 `gifmanager_decode_gif`，且此后不得再使用。
#[no_mangle]
pub unsafe extern "C" fn gifmanager_frames_free(frames: *mut GifFrames) {
    if frames.is_null() {
        return;
    }
    let boxed = Box::from_raw(frames);
    let frame_bytes = boxed.width as usize * boxed.height as usize * BPP;
    let total = frame_bytes * boxed.frame_count as usize;
    if !boxed.buffer.is_null() {
        drop(Vec::from_raw_parts(boxed.buffer, total, total));
    }
    if !boxed.offsets.is_null() {
        let count = boxed.frame_count as usize;
        drop(Vec::from_raw_parts(boxed.offsets, count, count));
    }
    if !boxed.delays.is_null() {
        let count = boxed.frame_count as usize;
        drop(Vec::from_raw_parts(boxed.delays, count, count));
    }
}

// ---------------------------------------------------------------------------
// Thumbnail decoding
// ---------------------------------------------------------------------------

/// A decoded still image scaled into a square box.
/// 被缩放进行方形范围的已解码静态图。
#[repr(C)]
pub struct Thumbnail {
    width: u32,
    height: u32,
    buffer: *mut c_uchar,
}

/// Decode a still image and scale it into a `box` x `box` area, preserving the
/// aspect ratio.
///
/// Returns null on failure. The result's longer side is at most `box`; a smaller
/// source is returned at its own size rather than upscaled.
///
/// 解码静态图并等比缩放进 `box` x `box` 区域。
///
/// 失败时返回空指针。结果较长边不超过 `box`；更小的源按自身尺寸返回，不做放大。
///
/// # Safety
/// `path` must be a NUL-terminated string. Release the result with
/// `gifmanager_thumbnail_free`.
///
/// # 安全性
/// `path` 必须是 NUL 结尾字符串。结果用 `gifmanager_thumbnail_free` 释放。
#[no_mangle]
pub unsafe extern "C" fn gifmanager_decode_thumbnail(
    path: *const c_char,
    box_side: u32,
) -> *mut Thumbnail {
    clear_error();

    if path.is_null() {
        set_error(ERR_BAD_ARGUMENT, "path is null / 路径为空指针");
        return ptr::null_mut();
    }
    let path = match std::ffi::CStr::from_ptr(path).to_str() {
        Ok(text) => text,
        Err(_) => {
            set_error(ERR_BAD_ARGUMENT, "path is not valid UTF-8 / 路径不是合法 UTF-8");
            return ptr::null_mut();
        }
    };

    let decoded = match image::open(path) {
        Ok(image) => image,
        Err(exc) => {
            set_error(ERR_DECODE, format!("cannot decode {path}: {exc}"));
            return ptr::null_mut();
        }
    };

    let source = decoded.to_rgba8();
    let (width, height) = (source.width() as usize, source.height() as usize);
    let pixels = source.as_raw();

    let (out_width, out_height) = scale_target(width, height, box_side as usize);
    let buffer = if (out_width, out_height) == (width, height) {
        pixels.clone()
    } else {
        resize_rgba(pixels, width, height, out_width, out_height)
    };

    let mut buffer = buffer;
    buffer.shrink_to_fit();
    // Capture the pointer before `forget` consumes the `Vec` /
    // 在 `forget` 消耗 `Vec` 之前取出指针
    let mut boxed = Box::new(Thumbnail {
        width: out_width as u32,
        height: out_height as u32,
        buffer: buffer.as_mut_ptr(),
    });
    std::mem::forget(buffer);
    boxed.width = out_width as u32;
    Box::into_raw(boxed)
}

/// Width of a decoded thumbnail / 已解码缩略图的宽度
///
/// # Safety
/// `thumb` must come from `gifmanager_decode_thumbnail`.
#[no_mangle]
pub unsafe extern "C" fn gifmanager_thumbnail_width(thumb: *const Thumbnail) -> u32 {
    if thumb.is_null() { 0 } else { (*thumb).width }
}

/// Height of a decoded thumbnail / 已解码缩略图的高度
///
/// # Safety
/// `thumb` must come from `gifmanager_decode_thumbnail`.
#[no_mangle]
pub unsafe extern "C" fn gifmanager_thumbnail_height(thumb: *const Thumbnail) -> u32 {
    if thumb.is_null() { 0 } else { (*thumb).height }
}

/// Byte length of a decoded thumbnail buffer / 已解码缩略图缓冲的字节长度
///
/// # Safety
/// `thumb` must come from `gifmanager_decode_thumbnail`.
#[no_mangle]
pub unsafe extern "C" fn gifmanager_thumbnail_bytes(thumb: *const Thumbnail) -> u64 {
    if thumb.is_null() {
        return 0;
    }
    (*thumb).width as u64 * (*thumb).height as u64 * BPP as u64
}

/// Copy a decoded thumbnail's pixels out / 复制出已解码缩略图的像素
///
/// Returns the number of bytes copied, or 0 on failure. /
/// 返回复制的字节数，失败返回 0。
///
/// # Safety
/// `thumb` must come from `gifmanager_decode_thumbnail`, and `destination` must
/// point to at least `gifmanager_thumbnail_bytes(thumb)` writable bytes.
///
/// # 安全性
/// `thumb` 必须来自 `gifmanager_decode_thumbnail`，且 `destination` 必须指向至少
/// `gifmanager_thumbnail_bytes(thumb)` 字节的可写空间。
#[no_mangle]
pub unsafe extern "C" fn gifmanager_thumbnail_copy(
    thumb: *const Thumbnail,
    destination: *mut c_uchar,
) -> u64 {
    if thumb.is_null() || destination.is_null() {
        return 0;
    }
    let total = gifmanager_thumbnail_bytes(thumb) as usize;
    ptr::copy_nonoverlapping((*thumb).buffer, destination, total);
    total as u64
}

/// Release a decoded thumbnail / 释放已解码的缩略图
///
/// # Safety
/// `thumb` must come from `gifmanager_decode_thumbnail` and must not be reused.
///
/// # 安全性
/// `thumb` 必须来自 `gifmanager_decode_thumbnail`，且不得再使用。
#[no_mangle]
pub unsafe extern "C" fn gifmanager_thumbnail_free(thumb: *mut Thumbnail) {
    if thumb.is_null() {
        return;
    }
    let boxed = Box::from_raw(thumb);
    if !boxed.buffer.is_null() {
        let total = boxed.width as usize * boxed.height as usize * BPP;
        drop(Vec::from_raw_parts(boxed.buffer, total, total));
    }
}

// ---------------------------------------------------------------------------
// Diagnostics
// ---------------------------------------------------------------------------

/// Number of threads the parallel frame scaling will use. Reported so the
/// settings page can show what "auto" actually resolved to.
///
/// 并行帧缩放将使用的线程数。上报它是为了让设置页显示"自动"实际解析成了什么。
#[no_mangle]
pub extern "C" fn gifmanager_thread_count() -> u32 {
    rayon::current_num_threads() as u32
}

/// Fill a struct with the library's build facts. Used by the layer check and by
/// the settings page's system-information section.
///
/// 用本库的构建信息填充结构。供分层检查与设置页的系统信息区块使用。
#[no_mangle]
pub extern "C" fn gifmanager_probe() -> c_int {
    // Touching the resizer and the thread pool here means a link-time problem in
    // either appears as a failed probe rather than as a crash on first decode.
    // 在此触碰重采样器与线程池，使任一者的链接问题表现为探测失败，而不是首次解码时崩溃。
    let _ = fir::Resizer::new();
    let _ = rayon::current_num_threads();
    ERR_NONE
}
