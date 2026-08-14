/* gifdec.c - Minimal GIF89a decoder exposed via a C ABI.
 * Used by GIFManager to decode GIF frames off the GUI thread (QMovie
 * decodes on the GUI thread, which is the main cause of scroll jank when
 * many animated stickers are visible).
 *
 * Written in plain C with malloc only: the bundled MinGW g++ 4.9.2 builds
 * DLLs whose libstdc++ operator new fails to initialize in modern
 * processes, so no C++ runtime is used here.
 * 最小 GIF89a 解码器，通过 C ABI 暴露给 GIFManager，用于在 GUI 线程之外
 * 解码 GIF 帧（QMovie 在 GUI 线程解码，是表情包多时滚动卡顿的主因）。
 * 纯 C + malloc 实现：内置 MinGW g++ 4.9.2 构建的 DLL 在现代进程中
 * libstdc++ 的 operator new 初始化会失败，因此这里不使用任何 C++ 运行时。 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#define EXPORT __declspec(dllexport)
#include <windows.h>
#include <wchar.h>
#else
#define EXPORT
#endif

typedef struct {
    int left, top, width, height;
    int delay_cs;        /* delay in centiseconds / 延时（百分之一秒） */
    int trans_index;     /* transparent palette index, -1 = none / 透明色索引，-1 = 无 */
    int disposal;        /* 0/1 keep, 2 background, 3 previous / 处置方式 */
    int interlace;
    int min_code;        /* LZW minimum code size / LZW 最小码长 */
    uint8_t* lzw;        /* LZW sub-block payload / LZW 数据 */
    size_t lzw_len;
    uint8_t* palette;    /* RGB triplets / RGB 三元组 */
    size_t pal_len;
} Frame;

typedef struct {
    int width, height;
    Frame* frames;
    size_t n_frames;
    uint8_t* data;       /* whole file bytes / 整个文件字节 */
    size_t data_len;
    int decoded_upto;    /* frames [0..decoded_upto] composited / 已合成的帧 */
    /* disposal state of the previous frame (persists across gif_frame calls)
     * 上一帧的处置状态（跨 gif_frame 调用持久保存） */
    int prev_disposal, prev_left, prev_top, prev_w, prev_h;
    uint8_t* canvas;     /* RGBA logical screen / RGBA 逻辑屏幕 */
    uint8_t* snapshot;   /* lazy copy for disposal==3 / disposal==3 快照 */
    size_t snapshot_cap;
    uint8_t* index_buf;  /* scratch index buffer / 索引暂存 */
    size_t index_cap;
} Gif;

static int rd_u16(const uint8_t* p) {
    return (int)p[0] | ((int)p[1] << 8);
}

/* Open a file for reading. On Windows the path is UTF-8 from Python, so
 * convert it to UTF-16 and use _wfopen (ANSI fopen fails on CJK paths).
 * Windows 下路径来自 Python 为 UTF-8，需转 UTF-16 用 _wfopen
 * （ANSI fopen 无法打开中文路径）。 */
static FILE* open_file(const char* path) {
#ifdef _WIN32
    int n = MultiByteToWideChar(CP_UTF8, 0, path, -1, NULL, 0);
    wchar_t* w = NULL;
    FILE* f;
    if (n <= 0) return NULL;
    w = (wchar_t*)malloc((size_t)n * sizeof(wchar_t));
    if (!w) return NULL;
    MultiByteToWideChar(CP_UTF8, 0, path, -1, w, n);
    f = _wfopen(w, L"rb");
    free(w);
    return f;
#else
    return fopen(path, "rb");
#endif
}

/* Read a whole file into a malloc'd buffer / 读取整个文件到 malloc 缓冲 */
static int read_file(const char* path, uint8_t** out, size_t* out_len) {
    FILE* f = open_file(path);
    long sz;
    size_t got;
    uint8_t* buf;
    *out = NULL;
    *out_len = 0;
    if (!f) return 0;
    if (fseek(f, 0, SEEK_END) != 0) { fclose(f); return 0; }
    sz = ftell(f);
    if (sz <= 0) { fclose(f); return 0; }
    if (fseek(f, 0, SEEK_SET) != 0) { fclose(f); return 0; }
    buf = (uint8_t*)malloc((size_t)sz);
    if (!buf) { fclose(f); return 0; }
    got = fread(buf, 1, (size_t)sz, f);
    fclose(f);
    if (got != (size_t)sz) { free(buf); return 0; }
    *out = buf;
    *out_len = (size_t)sz;
    return 1;
}

static void frame_clear(Frame* fr) {
    free(fr->lzw);
    free(fr->palette);
    fr->lzw = NULL;
    fr->palette = NULL;
    fr->lzw_len = 0;
    fr->pal_len = 0;
}

static void gif_free(Gif* g) {
    size_t i;
    if (!g) return;
    for (i = 0; i < g->n_frames; i++) frame_clear(&g->frames[i]);
    free(g->frames);
    free(g->data);
    free(g->canvas);
    free(g->snapshot);
    free(g->index_buf);
    free(g);
}

/* Append one frame record; returns 0 on alloc failure / 追加一帧记录 */
static int frames_push(Gif* g, Frame* fr) {
    Frame* nf = (Frame*)realloc(g->frames, (g->n_frames + 1) * sizeof(Frame));
    if (!nf) return 0;
    g->frames = nf;
    g->frames[g->n_frames] = *fr;
    g->n_frames++;
    return 1;
}

/* Parse the GIF structure (header, screen, extensions, image blocks)
 * 解析 GIF 结构（头、逻辑屏幕、扩展块、图像块） */
static int parse(Gif* g) {
    const uint8_t* d = g->data;
    size_t len = g->data_len;
    size_t pos = 0;
    int has_gct = 0;
    int gct_size = 0;
    uint8_t* gct = NULL;
    size_t gct_len = 0;
    int pend_delay = 0, pend_trans = -1, pend_disposal = 0, pend_has = 0;

    if (len < 13) return 0;
    if (memcmp(d, "GIF87a", 6) != 0 && memcmp(d, "GIF89a", 6) != 0) return 0;
    pos = 6;
    g->width = rd_u16(&d[pos]); pos += 2;
    g->height = rd_u16(&d[pos]); pos += 2;
    has_gct = (d[pos] & 0x80) != 0;
    gct_size = 2 << (d[pos] & 0x07);
    pos += 1;
    pos += 2;  /* background color index + pixel aspect / 背景色索引 + 像素宽高比 */
    if (has_gct && pos + (size_t)gct_size * 3 <= len) {
        gct = (uint8_t*)malloc((size_t)gct_size * 3);
        if (!gct) return 0;
        memcpy(gct, &d[pos], (size_t)gct_size * 3);
        gct_len = (size_t)gct_size * 3;
        pos += gct_len;
    }

    while (pos < len) {
        uint8_t b = d[pos++];
        if (b == 0x3B) break;  /* trailer / 结束符 */
        if (b == 0x21) {       /* extension / 扩展块 */
            uint8_t label;
            if (pos >= len) break;
            label = d[pos++];
            if (label == 0xF9) {  /* graphic control / 图形控制扩展 */
                uint8_t gpacked;
                /* pos points at the block-size byte; packed is at pos+1
                 * pos 指向块大小字节；packed 在 pos+1 */
                if (pos + 5 > len) break;
                gpacked = d[pos + 1];
                pend_delay = rd_u16(&d[pos + 2]);
                pend_trans = (gpacked & 0x01) ? (int)d[pos + 4] : -1;
                pend_disposal = (gpacked >> 2) & 0x07;
                pend_has = 1;
                pos += 5;
                if (pos < len && d[pos] == 0x00) pos++;  /* terminator / 结束符 */
            } else {
                /* skip sub-blocks / 跳过子块 */
                while (pos < len) {
                    uint8_t n = d[pos++];
                    if (n == 0) break;
                    pos += n;
                }
            }
        } else if (b == 0x2C) {  /* image descriptor / 图像描述符 */
            Frame fr;
            int lct = 0;
            int lct_size = 0;
            size_t pal_off = 0;
            size_t pal_n = 0;
            if (pos + 9 > len) break;
            memset(&fr, 0, sizeof(fr));
            fr.trans_index = -1;  /* default: no transparency / 默认无透明 */
            fr.left = rd_u16(&d[pos]);
            fr.top = rd_u16(&d[pos + 2]);
            fr.width = rd_u16(&d[pos + 4]);
            fr.height = rd_u16(&d[pos + 6]);
            lct = (d[pos + 8] & 0x80) != 0;
            fr.interlace = (d[pos + 8] & 0x40) != 0;
            lct_size = 2 << (d[pos + 8] & 0x07);
            pos += 9;
            if (lct && pos + (size_t)lct_size * 3 <= len) {
                pal_off = pos;
                pal_n = (size_t)lct_size * 3;
                pos += pal_n;
            } else if (gct != NULL) {
                pal_off = 0;
                pal_n = gct_len;
            }
            if (pos >= len) break;
            fr.min_code = d[pos++];
            /* LZW sub-blocks / LZW 数据子块 */
            {
                size_t cap = 256;
                int lzw_ok = 1;
                fr.lzw = (uint8_t*)malloc(cap);
                if (!fr.lzw) lzw_ok = 0;
                while (lzw_ok && pos < len) {
                    uint8_t n = d[pos++];
                    if (n == 0) break;
                    if (fr.lzw_len + n > cap) {
                        size_t ncap = cap * 2;
                        uint8_t* tmp;
                        while (fr.lzw_len + n > ncap) ncap *= 2;
                        tmp = (uint8_t*)realloc(fr.lzw, ncap);
                        if (!tmp) { lzw_ok = 0; break; }
                        fr.lzw = tmp;
                        cap = ncap;
                    }
                    memcpy(fr.lzw + fr.lzw_len, &d[pos], n);
                    fr.lzw_len += n;
                    pos += n;
                }
                if (!lzw_ok) {
                    frame_clear(&fr);
                    break;
                }
            }
            if (pal_n > 0) {
                fr.palette = (uint8_t*)malloc(pal_n);
                if (!fr.palette) { frame_clear(&fr); break; }
                if (pal_off > 0) memcpy(fr.palette, &d[pal_off], pal_n);
                else memcpy(fr.palette, gct, pal_n);
                fr.pal_len = pal_n;
            }
            if (pend_has) {
                fr.delay_cs = pend_delay;
                fr.trans_index = pend_trans;
                fr.disposal = pend_disposal;
                pend_has = 0;
            }
            if (fr.width <= 0 || fr.height <= 0) {
                frame_clear(&fr);
                continue;
            }
            if (!frames_push(g, &fr)) {
                frame_clear(&fr);
                break;
            }
        } else {
            break;  /* unexpected byte: stop parsing / 未知字节：停止解析 */
        }
    }
    free(gct);
    return g->n_frames > 0;
}

/* GIF LZW decode into a w*h index buffer / GIF LZW 解码到 w*h 索引缓冲 */
static int lzw_decode(const uint8_t* data, size_t data_len, int min_code,
                      int w, int h, uint8_t* out) {
    const int MAX_DICT = 4096;
    const int clear = 1 << min_code;
    const int eoi = clear + 1;
    int code_size = min_code + 1;
    int* prefix = NULL;
    uint8_t* suffix = NULL;
    uint8_t* first = NULL;
    uint8_t chain[4096];
    size_t bitpos = 0;
    size_t x = 0, y = 0;
    int next, prev = -1;
    int i;

    memset(out, 0, (size_t)w * h);
    if (!data || data_len == 0 || min_code < 2 || min_code > 8) return 0;
    prefix = (int*)malloc(MAX_DICT * sizeof(int));
    suffix = (uint8_t*)malloc(MAX_DICT);
    first = (uint8_t*)malloc(MAX_DICT);
    if (!prefix || !suffix || !first) {
        free(prefix); free(suffix); free(first);
        return 0;
    }
    for (i = 0; i < clear; i++) {
        prefix[i] = -1;
        suffix[i] = (uint8_t)i;
        first[i] = (uint8_t)i;
    }
    next = eoi + 1;

    for (;;) {
        int code = 0;
        size_t n;
        int guard;
        /* read one code (LSB first) / 读取一个码（LSB 在前） */
        if (bitpos + (size_t)code_size > data_len * 8) break;
        for (i = 0; i < code_size; i++) {
            size_t byte = bitpos >> 3;
            int bit = (data[byte] >> (bitpos & 7)) & 1;
            code |= bit << i;
            bitpos++;
        }
        if (code == clear) {
            code_size = min_code + 1;
            next = eoi + 1;
            prev = -1;
            continue;
        }
        if (code == eoi) break;
        if (prev < 0) {  /* first code after reset / 重置后的第一个码 */
            /* collect chain and emit / 收集链并输出 */
            int c = code;
            n = 0;
            guard = 0;
            while (c >= 0 && guard++ < MAX_DICT) {
                if (c >= next) { n = 0; break; }
                chain[n++] = suffix[c];
                c = prefix[c];
            }
            if (guard >= MAX_DICT) n = 0;
            for (i = (int)n - 1; i >= 0; i--) {
                if (x >= (size_t)w) { x = 0; y++; }
                if (y >= (size_t)h) break;
                out[y * (size_t)w + x] = chain[i];
                x++;
            }
            prev = code;
            continue;
        }
        /* New dictionary entry = chain(prev) + first char of chain(code)
         * 新字典项 = chain(prev) + chain(code) 的首字符 */
        if (code == next) {
            /* KwKwK case / KwKwK 特殊情况 */
            if (next < MAX_DICT) {
                prefix[next] = prev;
                suffix[next] = first[prev];
                first[next] = first[prev];
                next++;
            }
        } else if (code < next) {
            if (next < MAX_DICT) {
                prefix[next] = prev;
                suffix[next] = first[code];
                first[next] = first[prev];
                next++;
            }
        } else {
            break;  /* invalid code / 非法码 */
        }
        /* emit chain(code) / 输出 chain(code) */
        {
            int c = code;
            n = 0;
            guard = 0;
            while (c >= 0 && guard++ < MAX_DICT) {
                if (c >= next) { n = 0; break; }
                chain[n++] = suffix[c];
                c = prefix[c];
            }
            if (guard >= MAX_DICT) n = 0;
            for (i = (int)n - 1; i >= 0; i--) {
                if (x >= (size_t)w) { x = 0; y++; }
                if (y >= (size_t)h) break;
                out[y * (size_t)w + x] = chain[i];
                x++;
            }
        }
        prev = code;
        /* Grow the code size when the dictionary fills the current bit width
         * 字典达到当前位宽容量时增加码长 */
        if (next == (1 << code_size) && code_size < 12) code_size++;
    }
    free(prefix);
    free(suffix);
    free(first);
    return 1;
}

/* Interlace inverse mapping: screen row -> data row (LZW data is stored
 * in interlace pass order, so drawing screen row r needs data row inv[r]).
 * 隔行逆映射：屏幕行 -> 数据行（LZW 数据按隔行扫描的 pass 顺序存储，
 * 绘制屏幕行 r 需取数据行 inv[r]）。 */
static void build_interlace_map(int h, uint8_t* inv) {
    static const int starts[4] = {0, 4, 2, 1};
    static const int steps[4] = {8, 8, 4, 2};
    int p, r, n = 0;
    for (p = 0; p < 4 && n < h; p++) {
        for (r = starts[p]; r < h && n < h; r += steps[p]) {
            inv[r] = (uint8_t)n;
            n++;
        }
    }
}

static void clear_rect(uint8_t* canvas, int W, int H,
                       int l, int t, int w, int h) {
    int y, x;
    for (y = t; y < t + h; y++) {
        if (y < 0 || y >= H) continue;
        for (x = l; x < l + w; x++) {
            size_t o;
            if (x < 0 || x >= W) continue;
            o = ((size_t)y * W + x) * 4;
            canvas[o] = 0;
            canvas[o + 1] = 0;
            canvas[o + 2] = 0;
            canvas[o + 3] = 0;
        }
    }
}

static void snapshot_rect(const uint8_t* canvas, uint8_t* snap,
                          int W, int H, int l, int t, int w, int h) {
    int y, x;
    for (y = t; y < t + h; y++) {
        if (y < 0 || y >= H) continue;
        for (x = l; x < l + w; x++) {
            size_t src, dst;
            if (x < 0 || x >= W) continue;
            src = ((size_t)y * W + x) * 4;
            dst = ((size_t)(y - t) * w + (x - l)) * 4;
            snap[dst] = canvas[src];
            snap[dst + 1] = canvas[src + 1];
            snap[dst + 2] = canvas[src + 2];
            snap[dst + 3] = canvas[src + 3];
        }
    }
}

static void restore_rect(uint8_t* canvas, const uint8_t* snap,
                         int W, int H, int l, int t, int w, int h) {
    int y, x;
    for (y = t; y < t + h; y++) {
        if (y < 0 || y >= H) continue;
        for (x = l; x < l + w; x++) {
            size_t src, dst;
            if (x < 0 || x >= W) continue;
            src = ((size_t)(y - t) * w + (x - l)) * 4;
            dst = ((size_t)y * W + x) * 4;
            canvas[dst] = snap[src];
            canvas[dst + 1] = snap[src + 1];
            canvas[dst + 2] = snap[src + 2];
            canvas[dst + 3] = snap[src + 3];
        }
    }
}

/* Composite frames (decoded_upto+1 .. target) into the RGBA canvas
 * 把帧（decoded_upto+1 .. target）合成到 RGBA 画布 */
static int decode_upto(Gif* g, int target) {
    const int W = g->width, H = g->height;
    int i;
    if (g->n_frames == 0) return 0;
    if (target < 0) return 0;
    if (target >= (int)g->n_frames) target = (int)g->n_frames - 1;
    if (target <= g->decoded_upto) return 1;
    if (!g->canvas) {
        g->canvas = (uint8_t*)malloc((size_t)W * H * 4);
        if (!g->canvas) return 0;
        memset(g->canvas, 0, (size_t)W * H * 4);
    }
    for (i = g->decoded_upto + 1; i <= target; i++) {
        const Frame* fr = &g->frames[i];
        uint8_t* imap = NULL;
        int fw = fr->width, fh = fr->height;
        int py, px;
        /* apply the previous frame's disposal / 应用上一帧的处置方式 */
        if (g->prev_disposal == 2) {
            clear_rect(g->canvas, W, H, g->prev_left, g->prev_top,
                       g->prev_w, g->prev_h);
        } else if (g->prev_disposal == 3 && g->snapshot != NULL) {
            restore_rect(g->canvas, g->snapshot, W, H,
                         g->prev_left, g->prev_top, g->prev_w, g->prev_h);
        }
        if (fr->disposal == 3) {
            size_t need = (size_t)fw * fh * 4;
            if (g->snapshot_cap < need) {
                uint8_t* ns = (uint8_t*)realloc(g->snapshot, need);
                if (!ns) return 0;
                g->snapshot = ns;
                g->snapshot_cap = need;
            }
            snapshot_rect(g->canvas, g->snapshot, W, H,
                          fr->left, fr->top, fw, fh);
        }
        /* ensure index buffer / 确保索引缓冲足够 */
        if (g->index_cap < (size_t)fw * fh) {
            size_t need = (size_t)fw * fh;
            uint8_t* ni = (uint8_t*)realloc(g->index_buf, need);
            if (!ni) return 0;
            g->index_buf = ni;
            g->index_cap = need;
        }
        if (!lzw_decode(fr->lzw, fr->lzw_len, fr->min_code, fw, fh,
                        g->index_buf)) {
            return 0;
        }
        if (fr->interlace) {
            imap = (uint8_t*)malloc((size_t)fh);
            if (!imap) return 0;
            build_interlace_map(fh, imap);
        }
        for (py = 0; py < fh; py++) {
            int sy = fr->top + py;
            int src_row = fr->interlace ? imap[py] : py;
            if (sy < 0 || sy >= H) continue;
            for (px = 0; px < fw; px++) {
                int sx = fr->left + px;
                uint8_t idx;
                size_t o;
                if (sx < 0 || sx >= W) continue;
                idx = g->index_buf[src_row * fw + px];
                /* transparent pixel: keep the underlying canvas content
                 * (matches browsers and Pillow compositing)
                 * 透明像素：保留底层画布内容（与浏览器及 Pillow 合成一致） */
                if (idx == fr->trans_index) continue;
                if ((int)idx * 3 + 2 >= (int)fr->pal_len) continue;
                o = ((size_t)sy * W + sx) * 4;
                g->canvas[o] = fr->palette[idx * 3];
                g->canvas[o + 1] = fr->palette[idx * 3 + 1];
                g->canvas[o + 2] = fr->palette[idx * 3 + 2];
                g->canvas[o + 3] = 255;
            }
        }
        free(imap);
        g->prev_disposal = fr->disposal;
        g->prev_left = fr->left;
        g->prev_top = fr->top;
        g->prev_w = fw;
        g->prev_h = fh;
        g->decoded_upto = i;
    }
    return 1;
}

/* --- C ABI / C 接口 ----------------------------------------------------- */

/* Open a GIF file, return a handle (NULL on failure).
 * 打开 GIF 文件并返回句柄（失败返回 NULL）。 */
EXPORT void* gif_open(const char* path, int* out_w, int* out_h, int* out_frames) {
    Gif* g;
    if (!path || !out_w || !out_h || !out_frames) return NULL;
    g = (Gif*)malloc(sizeof(Gif));
    if (!g) return NULL;
    memset(g, 0, sizeof(Gif));
    g->decoded_upto = -1;  /* nothing composited yet / 尚未合成任何帧 */
    if (!read_file(path, &g->data, &g->data_len)) {
        free(g);
        return NULL;
    }
    if (!parse(g)) {
        gif_free(g);
        return NULL;
    }
    *out_w = g->width;
    *out_h = g->height;
    *out_frames = (int)g->n_frames;
    return g;
}

EXPORT int gif_frame_count(void* h) {
    Gif* g = (Gif*)h;
    return g ? (int)g->n_frames : 0;
}

/* Frame delay in milliseconds. Delays below 2 cs play as 100 ms, matching
 * Qt's QMovie behavior so playback speed stays consistent.
 * 帧延时（毫秒）。小于 2 百分之一秒的延时按 100ms 播放，与 Qt QMovie 一致。 */
EXPORT int gif_frame_delay_ms(void* h, int idx) {
    Gif* g = (Gif*)h;
    int cs;
    if (!g || idx < 0 || idx >= (int)g->n_frames) return 30;
    cs = g->frames[idx].delay_cs;
    if (cs < 2) return 100;
    return cs * 10;
}

/* Decode frame idx into out_rgba (width*height*4 bytes, RGBA8888).
 * Returns 1 on success. / 解码第 idx 帧到 out_rgba（w*h*4 字节 RGBA8888）。 */
EXPORT int gif_frame(void* h, int idx, uint8_t* out_rgba) {
    Gif* g = (Gif*)h;
    size_t n;
    if (!g || !out_rgba || idx < 0 || idx >= (int)g->n_frames) return 0;
    if (!decode_upto(g, idx)) return 0;
    n = (size_t)g->width * g->height * 4;
    memcpy(out_rgba, g->canvas, n);
    return 1;
}

EXPORT void gif_close(void* h) {
    gif_free((Gif*)h);
}
