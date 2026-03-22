import micropython

try:
    import jpeg
except ImportError:
    jpeg = None


@micropython.viper
def _rgb565be_to_rgbw(src, dst, dst_pixels: int, src_pixels: int, use_white: int):
    s = ptr8(src)
    d = ptr8(dst)
    for i in range(dst_pixels):
        r = 0
        g = 0
        b = 0
        w = 0
        if i < src_pixels:
            j = i << 1
            hi = int(s[j])
            lo = int(s[j + 1])
            val = (hi << 8) | lo
            r5 = (val >> 11) & 31
            g6 = (val >> 5) & 63
            b5 = val & 31
            r = (r5 * 527 + 23) >> 6
            g = (g6 * 259 + 33) >> 6
            b = (b5 * 527 + 23) >> 6
            if use_white != 0:
                w = r
                if g < w:
                    w = g
                if b < w:
                    w = b
                r -= w
                g -= w
                b -= w
        k = i << 2
        d[k] = r
        d[k + 1] = g
        d[k + 2] = b
        d[k + 3] = w


class JpegRGB565Decoder:
    def __init__(self, rotation=0, pixel_format="RGB565_BE", use_white=True):
        if jpeg is None:
            raise RuntimeError("jpeg module not available")
        self.decoder = jpeg.Decoder(rotation=rotation, pixel_format=pixel_format)
        self.use_white = bool(use_white)

    def decode_into_rgbw(self, jpeg_bytes, dst_rgbw, dst_pixels: int):
        decoded = self.decoder.decode(jpeg_bytes)
        src_pixels = len(decoded) >> 1
        _rgb565be_to_rgbw(decoded, dst_rgbw, int(dst_pixels), int(src_pixels), 1 if self.use_white else 0)
