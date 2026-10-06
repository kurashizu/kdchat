// Pictures of any common format -> an ImageBitmap (upright by EXIF): what the browser decodes itself (JPEG, PNG, GIF,
// WebP, AVIF, BMP), SVG / ICO through an <img>, HEIC / HEIF (phone photos) and TIFF with decoders that are only
// downloaded when such a file comes (heic2any: libheif, MIT/LGPL; UTIF: MIT).
import heicUrl from "heic2any/dist/heic2any.min.js?url";
import tiffUrl from "utif/UTIF.js?url";

export const ACCEPT = "image/*,.heic,.heif,.avif,.tif,.tiff,.svg,.ico,.bmp,.webp";
const EXT = /\.(jpe?g|png|gif|webp|avif|bmp|svg|ico|heic|heif|tiff?)$/i;

export function isPicture(f: File | Blob): boolean {
  return f.type.startsWith("image/") || ("name" in f && EXT.test((f as File).name));
}

const loaded: Record<string, Promise<void>> = {};
function script(url: string): Promise<void> {
  return (loaded[url] ??= new Promise((res, rej) => {
    const s = document.createElement("script");
    s.src = url;
    s.onload = () => res();
    s.onerror = () => rej(new Error("decoder did not load"));
    document.head.appendChild(s);
  }));
}

async function sniff(f: Blob): Promise<"heic" | "tiff" | null> {
  const b = new Uint8Array(await f.slice(0, 16).arrayBuffer());
  const ascii = (i: number, n: number) => String.fromCharCode(...b.slice(i, i + n));
  if (ascii(4, 4) === "ftyp" && /^(heic|heix|hevc|hevx|heim|heis|mif1|msf1)$/.test(ascii(8, 4))) return "heic";
  if ((b[0] === 0x49 && b[1] === 0x49 && b[2] === 0x2a && b[3] === 0) || (b[0] === 0x4d && b[1] === 0x4d && b[2] === 0 && b[3] === 0x2a)) return "tiff";
  return null;
}

function viaImg(f: Blob): Promise<ImageBitmap> {
  return new Promise((res, rej) => {
    const url = URL.createObjectURL(f);
    const img = new Image();
    img.onload = async () => {
      try {
        const w = img.naturalWidth || 512, h = img.naturalHeight || 512; // (an SVG without a size)
        const cv = document.createElement("canvas");
        cv.width = w;
        cv.height = h;
        cv.getContext("2d")!.drawImage(img, 0, 0, w, h);
        res(await createImageBitmap(cv));
      } catch (e) {
        rej(e);
      } finally {
        URL.revokeObjectURL(url);
      }
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      rej(new Error("unsupported picture format"));
    };
    img.src = url;
  });
}

export async function decodePicture(f: Blob): Promise<ImageBitmap> {
  const kind = await sniff(f);
  if (kind === "heic") {
    await script(heicUrl);
    const png = await (window as any).heic2any({ blob: f, toType: "image/png" });
    return createImageBitmap(Array.isArray(png) ? png[0] : png);
  }
  if (kind === "tiff") {
    await script(tiffUrl);
    const U = (window as any).UTIF;
    const buf = await f.arrayBuffer();
    const ifds = U.decode(buf);
    U.decodeImage(buf, ifds[0]);
    const rgba = new Uint8ClampedArray(U.toRGBA8(ifds[0]));
    return createImageBitmap(new ImageData(rgba, ifds[0].width, ifds[0].height));
  }
  try {
    return await createImageBitmap(f, { imageOrientation: "from-image" });
  } catch {
    return viaImg(f); // SVG, ICO, …
  }
}
