"""
     ██  ██████  ██    ██ ██ ███    ███ ███████ ████████ ██████  ██ ██   ██ 
     ██ ██    ██ ██    ██ ██ ████  ████ ██         ██    ██   ██ ██  ██ ██  
     ██ ██    ██ ██    ██ ██ ██ ████ ██ █████      ██    ██████  ██   ███  
██   ██ ██    ██  ██  ██  ██ ██  ██  ██ ██         ██    ██   ██ ██  ██ ██ 
 █████   ██████    ████   ██ ██      ██ ███████    ██    ██   ██ ██ ██   ██ 

               Procedural & Compositing Image Manipulation Nodes
                    http://www.github.com/amorano/jovimetrix

                    Copyright 2023 Alexander Morano (Joviex)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

GO NUTS; JUST TRY NOT TO DO IT IN YOUR HEAD.

@author: amorano
@title: Jovimetrix Composition Pack
@nickname: Jovimetrix
@description: Procedural & Compositing. Includes a Webcam node.
"""

import cv2
import torch
import numpy as np
from scipy.ndimage import rotate
from PIL import Image, ImageDraw, ImageChops, ImageFilter

import time
import logging
import concurrent.futures

log = logging.getLogger(__package__)
log.setLevel(logging.INFO)

# =============================================================================
# === CORE NODES ===
# =============================================================================

class JovimetrixBaseNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{}}

    DESCRIPTION = "A Jovimetrix Node"
    CATEGORY = "JOVIMETRIX 🔺🟩🔵"
    RETURN_TYPES = ("IMAGE", "MASK",)
    RETURN_NAMES = ("image", "mask",)
    OUTPUT_NODE = True
    FUNCTION = "run"

# wildcard trick is 100% stolen from pythongossss's
class AnyType(str):
    def __ne__(self, __value: object) -> bool:
        return False
WILDCARD = AnyType("*")

# =============================================================================
# === GLOBAL SUPPORTS ===
# =============================================================================

def deep_merge_dict(*dicts: dict) -> dict:
    """
    Deep merge multiple dictionaries recursively.
    """
    def _deep_merge(d1, d2):
        if not isinstance(d1, dict) or not isinstance(d2, dict):
            return d2

        merged_dict = d1.copy()

        for key in d2:
            if key in merged_dict:
                if isinstance(merged_dict[key], dict) and isinstance(d2[key], dict):
                    merged_dict[key] = _deep_merge(merged_dict[key], d2[key])
                elif isinstance(merged_dict[key], list) and isinstance(d2[key], list):
                    merged_dict[key].extend(d2[key])
                else:
                    merged_dict[key] = d2[key]
            else:
                merged_dict[key] = d2[key]
        return merged_dict

    merged = {}
    for d in dicts:
        merged = _deep_merge(merged, d)
    return merged

IT_REQUIRED = {
    "required": {}
}

IT_IMAGE = {
    "required": {
        "image": ("IMAGE", ),
    }
}

IT_MASK = {
    "required": {
        "mask": ("MASK", ),
    }
}

IT_PIXELS = {
    "required": {
        "pixels": (WILDCARD, {"default": None}),
    }
}

IT_PIXEL2 = {
    "required": {
        "pixelA": (WILDCARD, {"default": None}),
        "pixelB": (WILDCARD, {"default": None}),
    }
}

IT_WH = {
    "optional": {
        "width": ("INT", {"default": 256, "min": 64, "max": 4096, "step": 64}),
        "height": ("INT", {"default": 256, "min": 64, "max": 4096, "step": 64}),
    }
}

IT_WHMODE = {
    "optional": {
        "mode": (["NONE", "FIT", "CROP", "ASPECT"], {"default": "NONE"}),
    }
}

IT_TRANS = {
    "optional": {
        "offsetX": ("FLOAT", {"default": 0., "min": -1., "max": 1., "step": 0.05}),
        "offsetY": ("FLOAT", {"default": 0., "min": -1., "max": 1., "step": 0.05, "display": "number"}),
    }
}

IT_ROT = {
    "optional": {
        "angle": ("FLOAT", {"default": 0., "min": -180., "max": 180., "step": 5., "display": "number"}),
    }
}

IT_SCALE = {
    "optional": {
        "sizeX": ("FLOAT", {"default": 1., "min": 0.01, "max": 2., "step": 0.05}),
        "sizeY": ("FLOAT", {"default": 1., "min": 0.01, "max": 2., "step": 0.05}),
    }
}

IT_TILE = {
    "optional": {
        "tileX": ("INT", {"default": 1, "min": 0, "step": 1, "display": "number"}),
        "tileY": ("INT", {"default": 1, "min": 0, "step": 1}),
    }
}

IT_EDGE = {
    "optional": {
        "edge": (["CLIP", "WRAP", "WRAPX", "WRAPY"], {"default": "CLIP"}),
    }
}

IT_INVERT = {
    "optional": {
        "invert": ("FLOAT", {"default": 0., "min": 0., "max": 1., "step": 0.25}),
    }
}

IT_COLOR = {
    "optional": {
        "R": ("FLOAT", {"default": 1., "min": 0., "max": 1., "step": 0.1}),
        "G": ("FLOAT", {"default": 1., "min": 0., "max": 1., "step": 0.1}),
        "B": ("FLOAT", {"default": 1., "min": 0., "max": 1., "step": 0.1}),
    }
}

IT_TRS = deep_merge_dict(IT_TRANS, IT_ROT, IT_SCALE)

IT_WHMODEI = deep_merge_dict(IT_WH, IT_WHMODE, IT_INVERT)

# =============================================================================
# === MATRIX SUPPORT ===
# =============================================================================
def tensor2pil(image: torch.Tensor) -> Image:
    """Torch Tensor to PIL Image."""
    image = 255. * image.cpu().numpy().squeeze()
    image = np.clip(image, 0, 255)
    image = image.astype(np.uint8)
    return Image.fromarray(image)

def tensor2cv(image: torch.Tensor) -> cv2.Mat:
    """Torch Tensor to CV2 Matrix."""
    M = 255. * image.cpu().numpy().squeeze()
    image = Image.fromarray(np.clip(M, 0, 255).astype(np.uint8)) #.convert("RGB")
    return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)

def tensor2np(tensor: torch.Tensor) -> np.ndarray:
    """Torch Tensor to Numpy Array."""
    return np.clip(255.0 * tensor.cpu().numpy().squeeze(), 0, 255).astype(np.uint8)

def pil2tensor(image: Image) -> torch.Tensor:
    """PIL Image to Tensor RGB."""
    return torch.from_numpy(np.array(image).astype(np.float32) / 255.0).unsqueeze(0)

def pil2np(image: Image) -> np.ndarray:
    """PIL Image to Numpy Array."""
    return (np.array(image).astype(np.float32) / 255.0)[ :, :, :]

def pil2cv(image: Image) -> cv2.Mat:
    """PIL to CV2 Matrix."""
    return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)

def cv2pil(image: cv2.Mat) -> Image:
    """CV2 Matrix to PIL."""
    return Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))

def cv2tensor(image: cv2.Mat) -> torch.Tensor:
    """CV2 Matrix to Torch Tensor."""
    image = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    return torch.from_numpy(np.array(image).astype(np.float32) / 255.0).unsqueeze(0)

def cv2mask(image: cv2.Mat) -> torch.Tensor:
    """CV2 to Greyscale MASK."""
    image = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY))
    return torch.from_numpy(np.array(image).astype(np.float32) / 255.0).unsqueeze(0)

def np2tensor(image: np.ndarray) -> torch.Tensor:
    """NumPy to Torch Tensor."""
    return torch.from_numpy(image.astype(np.float32) / 255.0).unsqueeze(0)

# =============================================================================
# === SHAPE FUNCTIONS ===
# =============================================================================

def sh_body(func: str, width: int, height: int, sizeX=1., sizeY=1., fill=(255, 255, 255)) -> Image:
    sizeX = max(0.5, sizeX / 2 + 0.5)
    sizeY = max(0.5, sizeY / 2 + 0.5)
    xy = [(width * (1. - sizeX), height * (1. - sizeY)),(width * sizeX, height * sizeY)]
    image = Image.new("RGB", (width, height), 'black')
    d = ImageDraw.Draw(image)
    func = getattr(d, func)
    func(xy, fill=fill)
    return image

def sh_ellipse(width: int, height: int, sizeX=1., sizeY=1., fill=None) -> Image:
    return sh_body('ellipse', width, height, sizeX=sizeX, sizeY=sizeY, fill=fill)

def sh_quad(width: int, height: int, sizeX=1., sizeY=1., fill=None) -> Image:
    return sh_body('rectangle', width, height, sizeX=sizeX, sizeY=sizeY, fill=fill)

def sh_polygon(width: int, height: int, size: float=1., sides: int=3, angle: float=0., fill=None) -> Image:
    fill=fill or (255, 255, 255)
    size = max(0.00001, size)
    r = min(width, height) * size * 0.5
    xy = (width * 0.5, height * 0.5, r)
    image = Image.new("RGB", (width, height), 'black')
    d = ImageDraw.Draw(image)
    d.regular_polygon(xy, sides, fill=fill)
    return image

# =============================================================================
# === IMAGE FUNCTIONS ===
# =============================================================================

def rotate_ndarray(image, angle, clip=True):
    """."""
    rotated_image = rotate(image, angle, reshape=not clip, mode='constant', cval=0)

    if not clip:
        return rotated_image

    # Compute the dimensions for clipping
    height, width, _ = image.shape
    rotated_height, rotated_width, _ = rotated_image.shape

    # Calculate the difference in dimensions
    height_diff = rotated_height - height
    width_diff = rotated_width - width

    # Calculate the starting indices for clipping
    start_height = height_diff // 2
    start_width = width_diff // 2

    # Clip the rotated image
    return rotated_image[start_height:start_height + height, start_width:start_width + width]

def CROP(image: cv2.Mat, x1: int, y1: int, x2: int, y2: int) -> cv2.Mat:
    """."""
    height, width, _ = image.shape
    x1 = min(max(0, x1), width)
    x2 = min(max(0, x2), width)
    y1 = min(max(0, y1), height)
    y2 = min(max(0, y2), height)

    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1

    cropped = np.zeros((y2 - y1, x2 - x1, 3), dtype=np.uint8)
    image[y1:y2, x1:x2] = cropped
    return cropped

def CROP_CENTER(image: cv2.Mat, targetW: int, targetH: int) -> cv2.Mat:
    """AUTO Center CROP based on image and target size."""
    height, width, _ = image.shape
    h_center = int(height * 0.5)
    w_center = int(width * 0.5)
    w_delta = int(targetW * 0.5)
    h_delta = int(targetH * 0.5)
    return CROP(image, w_center - w_delta, h_center - h_delta, w_center + w_delta, h_center + h_delta)

def EDGEWRAP(image: cv2.Mat, tileX: float=1., tileY: float=1., edge: str="WRAP") -> cv2.Mat:
    """TILING."""
    height, width, _ = image.shape
    tileX = int(tileX * width * 0.5) if edge in ["WRAP", "WRAPX"] else 0
    tileY = int(tileY * height * 0.5) if edge in ["WRAP", "WRAPY"] else 0
    #log.info('EDGEWRAP', width, height, tileX, tileY)
    return cv2.copyMakeBorder(image, tileY, tileY, tileX, tileX, cv2.BORDER_WRAP)

def TRANSLATE(image: cv2.Mat, offsetX: float, offsetY: float) -> cv2.Mat:
    """TRANSLATION."""
    height, width, _ = image.shape
    M = np.float32([[1, 0, offsetX * width], [0, 1, offsetY * height]])
    #log.info('TRANSLATE', offsetX, offsetY)
    return cv2.warpAffine(image, M, (width, height), flags=cv2.INTER_LINEAR)

def ROTATE(image: cv2.Mat, angle: float, center=(0.5 ,0.5)) -> cv2.Mat:
    """ROTATION."""
    height, width, _ = image.shape
    center = (int(width * center[0]), int(height * center[1]))
    M = cv2.getRotationMatrix2D(center, -angle, 1.0)
    #log.info('ROTATE', angle)
    return cv2.warpAffine(image, M, (width, height), flags=cv2.INTER_LINEAR)

def SCALEFIT(image: cv2.Mat, width: int, height: int, mode: str="FIT") -> cv2.Mat:
    """Scale a matrix into a defined width, height explicitly or by a guiding edge."""
    h, w, _ = image.shape
    if w == width and h == height:
        return image
    if mode == "ASPECT":
        scalar = max(width, height)
        scalar /= max(w, h)
        return cv2.resize(image, None, fx=scalar, fy=scalar, interpolation=cv2.INTER_AREA)
    elif mode == "CROP":
        return CROP_CENTER(image, width, height)
    return cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)

def TRANSFORM(image: cv2.Mat, offsetX: float=0., offsetY: float=0., angle: float=0., sizeX: float=1., sizeY: float=1., edge:str='CLIP', widthT: int=256, heightT: int=256, mode: str='FIX') -> cv2.Mat:
    """Transform, Rotate and Scale followed by Tiling and then Inversion, conforming to an input wT, hT,."""
    height, width, _ = image.shape

    # SCALE
    if (sizeX != 1. or sizeY != 1.) and edge != "CLIP":
        tx = ty = 0
        if edge in ["WRAP", "WRAPX"] and sizeX < 1.:
            tx = 1. / sizeX - 1
            sizeX = 1.

        if edge in ["WRAP", "WRAPY"] and sizeY < 1.:
            ty = 1. / sizeY - 1
            sizeY = 1.
        image = EDGEWRAP(image, tx, ty)
        h, w, _ = image.shape
        #log.info('EDGEWRAP_POST', w, h)

    if sizeX != 1. or sizeY != 1.:
        wx = int(width * sizeX)
        hx = int(height * sizeY)
        #log.info('SCALE', wx, hx)
        image = cv2.resize(image, (wx, hx), interpolation=cv2.INTER_AREA)

    if edge != "CLIP":
        image = CROP_CENTER(image, width, height)

    # TRANSLATION
    if offsetX != 0. or offsetY != 0.:
        if edge != "CLIP":
            image = EDGEWRAP(image)
        image = TRANSLATE(image, offsetX, offsetY)
        if edge != "CLIP":
            image = CROP_CENTER(image, width, height)

    # ROTATION
    if angle != 0:
        if edge != "CLIP":
            image = EDGEWRAP(image)
        image = ROTATE(image, angle)

    return SCALEFIT(image, widthT, heightT, mode=mode)

def INVERT(image: cv2.Mat, invert: float=1.) -> cv2.Mat:
    invert = min(max(invert, 0.), 1.)
    inverted = np.abs(255 - image)
    return cv2.addWeighted(image, 1. - invert, inverted, invert, 0)

def GAMMA(image: cv2.Mat, value: float) -> cv2.Mat:
    gamma_inv = 1. / max(0.01, min(0.9999999, value))
    return image.pow(gamma_inv)

def CONTRAST(image: cv2.Mat, value: float) -> cv2.Mat:
    image = (image - 0.5) * value + 0.5
    return torch.clamp(image, 0.0, 1.0)

def EXPOSURE(image: cv2.Mat, value: float) -> cv2.Mat:
    return image * (2.0**(value))

def HSV(image: cv2.Mat, hue, saturation, value) -> cv2.Mat:
    image = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    hue *= 255
    image[:, :, 0] = (image[:, :, 0] + hue) % 180
    image[:, :, 1] = np.clip(image[:, :, 1] * saturation, 0, 255)
    image[:, :, 2] = np.clip(image[:, :, 2] * value, 0, 255)
    return cv2.cvtColor(image, cv2.COLOR_HSV2BGR)

def MIRROR(image: cv2.Mat, pX: float, axis: int, invert: bool=False) -> cv2.Mat:
    output =  np.zeros_like(image)
    flip = cv2.flip(image, axis)
    height, width, _ = image.shape

    pX = min(max(pX, 0), 1)
    if invert:
        pX = 1 - pX
        flip, image = image, flip

    scalar = height if axis == 0 else width
    slice1 = int(pX * scalar)
    slice1w = scalar - slice1
    slice2w = min(scalar - slice1w, slice1w)

    if axis == 0:
        output[:slice1, :] = image[:slice1, :]
        output[slice1:slice1 + slice2w, :] = flip[slice1w:slice1w + slice2w, :]
    else:
        output[:, :slice1] = image[:, :slice1]
        output[:, slice1:slice1 + slice2w] = flip[:, slice1w:slice1w + slice2w]

    if invert:
        output = cv2.flip(output, axis)

    return output

def EXTEND(imageA: cv2.Mat, imageB: cv2.Mat, axis: int=0, flip: bool=False) -> cv2.Mat:
    if flip:
        imageA, imageB = imageB, imageA
    axis = 1 if axis == "HORIZONTAL" else 0
    return np.concatenate((imageA, imageB), axis=axis)

# =============================================================================
# === NODES ===
# =============================================================================

class TransformNode(JovimetrixBaseNode):
    @classmethod
    def INPUT_TYPES(cls):
        return deep_merge_dict(IT_PIXELS, IT_TRS, IT_EDGE, IT_WH, IT_WHMODE)

    DESCRIPTION = "Translate, Rotate, Scale, Tile and Invert an input. All options allow for CROP or WRAPing of the edges."

    def run(self, pixels, offsetX, offsetY, angle, sizeX, sizeY, edge, width, height, mode):
        pixels = tensor2cv(pixels)
        pixels = TRANSFORM(pixels, offsetX, offsetY, angle, sizeX, sizeY, edge, width, height, mode)
        return (cv2tensor(pixels), cv2mask(pixels), )

class TileNode(JovimetrixBaseNode):
    @classmethod
    def INPUT_TYPES(cls):
        return deep_merge_dict(IT_PIXELS, IT_TILE)

    DESCRIPTION = "Tile an Image with optional crop to original image size."
    CATEGORY = "JOVIMETRIX 🔺🟩🔵"

    def run(self, pixels, tileX, tileY):
        pixels = tensor2cv(pixels)
        height, width, _ = pixels.shape
        pixels = EDGEWRAP(pixels, tileX, tileY)
        # rebound to target width and height
        pixels = cv2.resize(pixels, (width, height))
        return (cv2tensor(pixels), cv2mask(pixels), )

class ShapeNode(JovimetrixBaseNode):
    @classmethod
    def INPUT_TYPES(cls):
        d = {
            "required": {
                "shape": (["CIRCLE", "SQUARE", "ELLIPSE", "RECTANGLE", "POLYGON"], {"default": "SQUARE"}),
                "sides": ("INT", {"default": 3, "min": 3, "max": 100, "step": 1}),
            },
        }
        return deep_merge_dict(d, IT_WH, IT_COLOR, IT_ROT, IT_SCALE, IT_INVERT)

    DESCRIPTION = ""
    CATEGORY = "JOVIMETRIX 🔺🟩🔵"
    RETURN_TYPES = ("IMAGE", "MASK", )
    RETURN_NAMES = ("image", "mask", )

    def run(self, shape, sides, width, height, R, G, B, angle, sizeX, sizeY, invert):
        image = None
        fill = (int(R * 255.),
                int(G * 255.),
                int(B * 255.),)

        match shape:
            case 'SQUARE':
                image = sh_quad(width, height, sizeX, sizeX, fill=fill)

            case 'ELLIPSE':
                image = sh_ellipse(width, height, sizeX, sizeY, fill=fill)

            case 'RECTANGLE':
                image = sh_quad(width, height, sizeX, sizeY, fill=fill)

            case 'POLYGON':
                image = sh_polygon(width, height, sizeX, sides, fill=fill)

            case _:
                image = sh_ellipse(width, height, sizeX, sizeX, fill=fill)

        image = image.rotate(-angle)
        if invert > 0.:
            image = pil2cv(image)
            image = INVERT(image, invert)
            image = cv2pil(image)

        return (pil2tensor(image), pil2tensor(image.convert("L")), )

class ConstantNode(JovimetrixBaseNode):
    @classmethod
    def INPUT_TYPES(cls):
        return deep_merge_dict(IT_REQUIRED, IT_WH, IT_COLOR)

    DESCRIPTION = ""
    CATEGORY = "JOVIMETRIX 🔺🟩🔵"

    def run(self, width, height, R, G, B):
        image = Image.new("RGB", (width, height), (int(R * 255.), int(G * 255.), int(B * 255.)) )
        return (pil2tensor(image),)

class PixelShaderBaseNode(JovimetrixBaseNode):
    @classmethod
    def INPUT_TYPES(cls):
        d = {"required": {},
            "optional": {
                "R": ("STRING", {"multiline": True, "default": "1. - np.minimum(1, np.sqrt((($u-0.5)**2 + ($v-0.5)**2) * 2))"}),
                "G": ("STRING", {"multiline": True}),
                "B": ("STRING", {"multiline": True}),
            },
        }
        if cls == PixelShaderImageNode:
            return deep_merge_dict(IT_IMAGE, d, IT_WH)
        return deep_merge_dict(d, IT_WH)

    @staticmethod
    def shader(image: cv2.Mat, width: int, height: int, R: str, G: str, B: str):
        import math
        from ast import literal_eval

        R = R.lower().strip()
        G = G.lower().strip()
        B = B.lower().strip()

        def parseChannel(chan, x, y) -> str:
            """
            x, y - current x,y position (output)
            u, v - tex-coord position (output)
            w, h - width/height (output)
            i    - value in original image at (x, y)
            """
            exp = chan.replace("$x", str(x))
            exp = exp.replace("$y", str(y))
            exp = exp.replace("$u", str(x/width))
            exp = exp.replace("$v", str(y/height))
            exp = exp.replace("$w", str(width))
            exp = exp.replace("$h", str(height))
            ir, ig, ib, = image[y, x]
            exp = exp.replace("$r", str(ir))
            exp = exp.replace("$g", str(ig))
            exp = exp.replace("$b", str(ib))
            return exp

        # Define the pixel shader function
        def pixel_shader(x, y):
            result = []
            for i, who in enumerate((B, G, R, )):
                if who == "":
                    result.append(image[y, x][i])
                    continue

                exp = parseChannel(who, x, y)
                try:
                    i = literal_eval(exp)
                    result.append(int(i * 255))
                except:
                    try:
                        i = eval(exp.replace("^", "**"))
                        result.append(int(i * 255))
                    except Exception as e:
                        log.error(str(e))
                        result.append(image[y, x][i])
                        continue

            return result

        # Create an empty numpy array to store the pixel values
        ret = np.zeros((height, width, 3), dtype=np.uint8)

        # Function to process a chunk in parallel
        def process_chunk(chunk_coords):
            y_start, y_end, x_start, x_end = chunk_coords
            for y in range(y_start, y_end):
                for x in range(x_start, x_end):
                    ret[y, x] = pixel_shader(x, y)

        # 12 seems to be the legit balance *for single node
        chunkX = chunkY = 8

        # Divide the image into chunks
        chunk_coords = []
        for y in range(0, height, chunkY):
            for x in range(0, width, chunkX):
                y_end = min(y + chunkY, height)
                x_end = min(x + chunkX, width)
                chunk_coords.append((y, y_end, x, x_end))

        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = {executor.submit(process_chunk, chunk): chunk for chunk in chunk_coords}
            for _ in concurrent.futures.as_completed(futures):
                pass

        return ret

    def run(self, image: torch.tensor, width: int, height: int, R: str, G: str, B: str) -> torch.tensor:
        image = tensor2cv(image)
        image = PixelShaderBaseNode.shader(image, width, height, R, G, B)
        return (cv2tensor(image), cv2mask(image), )

class PixelShaderNode(PixelShaderBaseNode):
    DESCRIPTION = ""
    def run(self, width: int, height: int, R: str, G: str, B: str) -> torch.tensor:
        image = torch.zeros((height, width, 3), dtype=torch.uint8)
        return super().run(image, width, height, R, G, B)

class PixelShaderImageNode(PixelShaderBaseNode):
    DESCRIPTION = ""
    def run(self, image: torch.tensor, width: int, height: int, R: str, G: str, B: str) -> torch.tensor:
        image = tensor2cv(image)
        image = cv2.resize(image, (width, height))
        image = cv2tensor(image)
        return super().run(image, width, height, R, G, B)

class MirrorNode(JovimetrixBaseNode):
    @classmethod
    def INPUT_TYPES(cls):
        d = {"required": {
                "x": ("FLOAT", {"default": 0.5, "min": 0., "max": 1., "step": 0.05}),
                "y": ("FLOAT", {"default": 0.5, "min": 0., "max": 1., "step": 0.05}),
                "mode": (["X", "Y", "XY", "YX"], {"default": "X"}),
            },
        }
        return deep_merge_dict(IT_PIXELS, d, IT_INVERT)

    DESCRIPTION = "Flip an input across the X axis, the Y Axis or both, with independant centers."

    def run(self, pixels, x, y, mode, invert):
        pixels = tensor2cv(pixels)
        while (len(mode) > 0):
            axis, mode = mode[0], mode[1:]
            px = [y, x][axis == 'X']
            pixels = MIRROR(pixels, px, int(axis == 'X'), invert=invert)
        return (cv2tensor(pixels), cv2mask(pixels), )

class HSVNode(JovimetrixBaseNode):
    @classmethod
    def INPUT_TYPES(cls):
        d = {
            "optional": {
                "hue": ("FLOAT",{"default": 0., "min": 0., "max": 1., "step": 0.01},),
                "saturation": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 100.0, "step": 0.01}, ),
                "value": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 100.0, "step": 0.01}, ),
            }
        }
        return deep_merge_dict(IT_IMAGE, d)

    DESCRIPTION = "Tweak the Hue, Saturation and Value for an Image."

    def run(self, image, hue, saturation, value):
        image = tensor2cv(image)
        if hue != 0. or saturation != 1. or value != 1.:
            image = HSV(image, hue, saturation, value)
        return (cv2tensor(image),)

class ExtendNode(JovimetrixBaseNode):
    @classmethod
    def INPUT_TYPES(cls):
        d = {"required": {
                "axis": (["HORIZONTAL", "VERTICAL"], {"default": "HORIZONTAL"}),
            },
            "optional": {
                "flip": ("BOOLEAN", {"default": False}),
            },
        }
        return deep_merge_dict(IT_PIXEL2, d, IT_WH, IT_WHMODE)

    DESCRIPTION = "Contrast, Gamma and Exposure controls for images."

    def run(self, pixelA, pixelB, axis, flip, width, height, mode):
        pixelA = tensor2cv(pixelA)
        pixelB = tensor2cv(pixelB)
        pixelA = EXTEND(pixelA, pixelB, axis, flip)
        if mode != "NONE":
            pixelA = SCALEFIT(pixelA, width, height, mode)
        return (cv2tensor(pixelA), cv2mask(pixelA), )

class BlendNode(JovimetrixBaseNode):
    OPS = {
        'LERP': Image.blend,
        'ADD': ImageChops.add,
        'MINIMUM': ImageChops.darker,
        'MAXIMUM': ImageChops.lighter,
        'MULTIPLY': ImageChops.multiply,
        'SOFT LIGHT': ImageChops.soft_light,
        'HARD LIGHT': ImageChops.hard_light,
        'OVERLAY': ImageChops.overlay,
        'SCREEN': ImageChops.screen,
        'SUBTRACT': ImageChops.subtract,
        'DIFFERENCE': ImageChops.difference,
        'LOGICAL AND': np.bitwise_and,
        'LOGICAL OR': np.bitwise_or,
        'LOGICAL XOR': np.bitwise_xor,
    }

    @classmethod
    def INPUT_TYPES(cls):
        d = {"required": {
                    "imageA": ("IMAGE", ),
                    "imageB": ("IMAGE", ),
                    "alpha": ("FLOAT", {"default": 1., "min": 0., "max": 1., "step": 0.01}),
                },
                "optional": {
                    "func": (list(BlendNode.OPS.keys()), {"default": "LERP"}),
                    "modeA": (["FIT", "CROP", "ASPECT"], {"default": "FIT"}),
                    "modeB": (["FIT", "CROP", "ASPECT"], {"default": "FIT"}),
            }}
        return deep_merge_dict(d, IT_WHMODEI)

    DESCRIPTION = "Takes 2 Image inputs and an apha and performs a linear blend (alpha) between both images based on the selected operations."

    @staticmethod
    def blend(maskA, maskB, alpha, func):
        if (op := BlendNode.OPS.get(func, None)) is None:
            return maskA
        alpha = min(max(alpha, 0.), 1.)
        if func == 'LERP':
            maskA = cv2pil(maskA)
            maskB = cv2pil(maskB)
            maskA = op(maskA, maskB, alpha)
            maskA = pil2cv(maskA)
        elif func.startswith("LOGICAL"):
            maskA = np.array(maskA)
            maskB = np.array(maskB)
            maskA = op(maskA, maskB)
            maskA = Image.fromarray(maskA)
            maskA = pil2cv(maskA)
        else:
            maskA = cv2pil(maskA)
            maskB = cv2pil(maskB)
            if func == 'MULTIPLY':
                maskB = maskB.point(lambda i: 255 - int(i * alpha))
            else:
                maskB = maskB.point(lambda i: int(i * alpha))
            maskA = pil2cv(op(maskA, maskB))
        return maskA

    def run(self, imageA: torch.tensor, imageB: torch.tensor, alpha: float, func, modeA, modeB, width, height, mode, invert) -> (torch.tensor, torch.tensor):
        imageA = tensor2cv(imageA)
        imageB = tensor2cv(imageB)
        imageA = SCALEFIT(imageA, width, height, modeA)
        imageB = SCALEFIT(imageB, width, height, modeB)
        imageA = BlendNode.blend(imageA, imageB, alpha, func)
        if invert:
            imageA = INVERT(imageA, invert)
        imageA = SCALEFIT(imageA, width, height, mode)
        return (cv2tensor(imageA), cv2mask(imageA),)

class AdjustNode(JovimetrixBaseNode):
    OPS = {
        'BLUR': ImageFilter.GaussianBlur,
        'SHARPEN': ImageFilter.UnsharpMask,
    }

    OPS_PRE = {
        # PREDEFINED
        'EMBOSS': ImageFilter.EMBOSS,
        'FIND_EDGES': ImageFilter.FIND_EDGES,
    }

    OPS_CV2 = {
        'CONTRAST': CONTRAST,
        'GAMMA': GAMMA,
        'EXPOSURE': EXPOSURE,
        'INVERT': None,
    }

    @classmethod
    def INPUT_TYPES(cls):
        ops = list(AdjustNode.OPS.keys()) + list(AdjustNode.OPS_PRE.keys()) + list(AdjustNode.OPS_CV2.keys())
        d = {"required": {
                "func": (ops, {"default": "BLUR"}),
            },
            "optional": {
                "radius": ("INT", {"default": 1, "min": 0, "step": 1}),
                "alpha": ("FLOAT",{"default": 1., "min": 0., "max": 1., "step": 0.02},),
        }}
        return deep_merge_dict(IT_PIXELS, d)

    DESCRIPTION = "A single node with multiple operations."

    def run(self, pixels, func, radius, alpha)  -> (torch.tensor, torch.tensor):
        if (op := AdjustNode.OPS.get(func, None)):
           pixels = tensor2pil(pixels)
           pixels = pixels.filter(op(radius))
        elif (op := AdjustNode.OPS_PRE.get(func, None)):
            pixels = tensor2pil(pixels)
            pixels = pixels.filter(op())
        else:
            if func == 'INVERT':
                pixels = tensor2cv(pixels)
                pixels = INVERT(pixels, alpha)
                pixels = cv2pil(pixels)
            else:
                op = AdjustNode.OPS_CV2[func]
                pixels = op(pixels, alpha)
                pixels = tensor2pil(pixels)
        return (pil2tensor(pixels), pil2tensor(pixels.convert("L")), )

class ProjectionNode(JovimetrixBaseNode):
    @classmethod
    def INPUT_TYPES(cls):
        d = {"required": {
                "proj": (["SPHERICAL", "CYLINDRICAL"], {"default": "SPHERICAL"}),
            }}
        return deep_merge_dict(IT_IMAGE, d, IT_WH)

    DESCRIPTION = ""

    def run(self, image, proj, width, height):
        image = tensor2pil(image)

        source_width, source_height = image.size
        target_image = Image.new("RGB", (width, height))
        for y_target in range(height):
            for x_target in range(width):
                x_source = int((x_target / width) * source_width)

                if proj == "SPHERICAL":
                    x_source %= source_width
                y_source = int(y_target / height * source_height)
                px = image.getpixel((x_source, y_source))

                target_image.putpixel((x_target, y_target), px)
        return (pil2tensor(target_image),)

class RouteNode(JovimetrixBaseNode):
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "o": (WILDCARD, {"default": None}),
        }}

    DESCRIPTION = ""
    RETURN_TYPES = (WILDCARD,)
    RETURN_NAMES = ("🚌",)

    def run(self, o):
        return (o,)

class WebCamNode(JovimetrixBaseNode):
    MAXCAM = 5
    MAXFPS = 60
    CAMERA = {i: None for i in range(MAXCAM)}
    CAMFPS = {i: 12 for i in range(MAXCAM)}

    @classmethod
    def INPUT_TYPES(cls):
        d = {"required": {
            "cam": ("INT", {"min": 0, "max": WebCamNode.MAXCAM-1, "step":1, "default": 0}),
            "rate": ("INT", {"min": 1, "max": 60, "step": 1, "default": WebCamNode.MAXFPS}),
            "pause": ("BOOLEAN", {"default": False})
        }}
        return deep_merge_dict(d, IT_WH, IT_WHMODE)

    @classmethod
    def INIT(cls, camIdx: int, rate: float):
        try:
            camera = WebCamNode.CAMERA[camIdx]
        except KeyError as _:
            log.warn(f"initialize camera out of range {camIdx}")
            return

        if camera:
            log.warn(f"Camera already captured {camIdx}")
            return camera

        camera = cv2.VideoCapture(camIdx)
        if camera is None or not camera.isOpened():
            log.warn(f"cannot open webcam {camIdx}")
            return

        WebCamNode.CAMERA[camIdx] = camera
        WebCamNode.FRAMERATE(camIdx, rate)

    @classmethod
    def FRAMERATE(cls, cam: int, rate: float):
        if WebCamNode.CAMERA[cam] and WebCamNode.CAMERA[cam].isOpened() and rate != WebCamNode.CAMFPS[cam]:
            WebCamNode.CAMERA.set(cv2.CAP_PROP_FPS, rate)
            WebCamNode.CAMFPS[cam] = rate
            log.info('CAMERA RATE CHANGE', cam, rate)

    @classmethod
    def IS_CHANGED(cls, cam: int, rate: float, width: int, height: int, mode: str, pause: bool):
        if WebCamNode.CAMERA[cam] is None:
            cls.INIT(cam, rate)
        if rate != WebCamNode.CAMFPS[cam]:
            cls.FRAMERATE(cam, rate)
        return float("nan")

    def __init__(self):
        self.__last = None
        self.__camera = None
        self.__pause = False

    def __del__(self):
        if self.__camera:
            log.info("releasing camera")
            self.__camera.RELEASE(self.__camera)
        self.__camera = None

    def run(self, cam, rate, width, height, mode, pause):
        self.__pause = pause
        if pause:
            return self.__last

        if self.__camera is None:
            self.__camera = WebCamNode.INIT(cam, rate)
            image = torch.zeros((height, width, 3), dtype=torch.uint8)
            image = tensor2cv(image)
            self.__last = (cv2tensor(image), cv2mask(image), )
            time.sleep(0.2)

        if not self.__pause:
            if self.__camera is None:
                log.warn(f"Failed to read webcam {cam}")
                return self.__last

            ret, image = self.__camera.read()
            if not ret:
                log.warn(f"Failed to read webcam {cam}")
                return self.__last

            image = SCALEFIT(image, width, height, mode=mode)
            self.__last = (cv2tensor(image), cv2mask(image), )

        self.__pause = pause
        return self.__last

NODE_CLASS_MAPPINGS = {
    "🟪 Constant (jov)": ConstantNode,
    "✨ Shape Generator (jov)": ShapeNode,
    "🔆 Pixel Shader (jov)": PixelShaderNode,
    "🔆 Pixel Shader Image (jov)": PixelShaderImageNode,

    "🌱 Transform (jov)": TransformNode,
    "🔳 Tile (jov)": TileNode,
    "🔰 Mirror (jov)": MirrorNode,

    "🌈 HSV (jov)": HSVNode,
    "🕸️ Adjust (jov)": AdjustNode,

    "🎇 Expand (jov)": ExtendNode,

    "⚗️ Blend (jov)": BlendNode,

    # "🗺️ Projection (jov)": ProjectionNode,

    "🚌 Route (jov)": RouteNode,

    "📷 WebCam (jov)": WebCamNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {k: k for k in NODE_CLASS_MAPPINGS}