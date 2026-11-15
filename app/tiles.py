"""Tile cutting, poster fitting and PDF/PNG export (Pillow)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.layout import Layout, Tile


def to_rgb(
    img: Image.Image, background: tuple[int, int, int] = (255, 255, 255)
) -> Image.Image:
    """RGB copy of img with any transparency flattened onto background."""
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        base = Image.new("RGB", img.size, background)
        rgba = img.convert("RGBA")
        base.paste(rgba, mask=rgba.split()[3])
        return base
    return img.convert("RGB")


def poster_to_source(
    layout: Layout, src_size: tuple[int, int], fill: bool
) -> tuple[float, float, float]:
    """How fit_to_poster places a source: returns (scale, off_x, off_y).

    A poster pixel (x, y) shows source point ((x + off_x) / scale, (y + off_y) / scale).
    """
    pw, ph = layout.poster_w_px, layout.poster_h_px
    src_w, src_h = src_size
    rx, ry = pw / src_w, ph / src_h
    scale = max(rx, ry) if fill else min(rx, ry)
    new_w, new_h = round(src_w * scale), round(src_h * scale)
    if fill:
        return scale, (new_w - pw) // 2, (new_h - ph) // 2
    return scale, -((pw - new_w) // 2), -((ph - new_h) // 2)


def fit_to_poster(
    img: Image.Image,
    layout: Layout,
    fill: bool,
    background: tuple[int, int, int] = (255, 255, 255),
) -> Image.Image:
    """Return an RGB image exactly poster_w_px x poster_h_px.

    fill=True: scale to cover then center-crop.
    fill=False: scale to contain and paste centered on background.
    Alpha channel is flattened onto the background colour.
    """
    pw, ph = layout.poster_w_px, layout.poster_h_px
    img = to_rgb(img, background)
    src_w, src_h = img.size

    if fill:
        rx, ry = pw / src_w, ph / src_h
        scale = max(rx, ry)
        new_w, new_h = round(src_w * scale), round(src_h * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        left = (new_w - pw) // 2
        top = (new_h - ph) // 2
        img = img.crop((left, top, left + pw, top + ph))
    else:
        rx, ry = pw / src_w, ph / src_h
        scale = min(rx, ry)
        new_w, new_h = round(src_w * scale), round(src_h * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        canvas = Image.new("RGB", (pw, ph), background)
        paste_x = (pw - new_w) // 2
        paste_y = (ph - new_h) // 2
        canvas.paste(img, (paste_x, paste_y))
        img = canvas

    return img


def cut_tiles(
    poster: Image.Image,
    layout: Layout,
    marks: bool = True,
) -> list[Image.Image]:
    """Cut the poster into tile images (row-major order).

    When marks=True and overlap_px > 0, draws alignment ticks and labels on the
    tile that will be UNDERNEATH its neighbour.
    """
    images: list[Image.Image] = []

    tick_len = layout.overlap_px
    tick_w = max(1, round(layout.dpi / 150))

    for tile in layout.tiles:
        region = poster.crop((
            tile.src.x,
            tile.src.y,
            tile.src.x + tile.src.w,
            tile.src.y + tile.src.h,
        ))
        tile_img = region.copy()

        if marks and layout.overlap_px > 0:
            draw = ImageDraw.Draw(tile_img)
            has_right = tile.col < layout.cols - 1
            has_bottom = tile.row < layout.rows - 1

            if has_right:
                # Two vertical hairlines at x = tile_w - overlap_px (inside overlap strip).
                x = layout.tile_w_px - layout.overlap_px
                draw.rectangle(
                    [x, 0, x + tick_w - 1, tick_len - 1],
                    fill=(0, 0, 0),
                )
                draw.rectangle(
                    [x, layout.tile_h_px - tick_len, x + tick_w - 1, layout.tile_h_px - 1],
                    fill=(0, 0, 0),
                )

            if has_bottom:
                # Two horizontal hairlines at y = tile_h - overlap_px (inside overlap strip).
                y = layout.tile_h_px - layout.overlap_px
                draw.rectangle(
                    [0, y, tick_len - 1, y + tick_w - 1],
                    fill=(0, 0, 0),
                )
                draw.rectangle(
                    [layout.tile_w_px - tick_len, y, layout.tile_w_px - 1, y + tick_w - 1],
                    fill=(0, 0, 0),
                )

            # Sheet label, always inside a strip the neighbouring sheet will cover.
            if has_right or has_bottom:
                label = f"{tile.row + 1}-{tile.col + 1}"
                font_size = max(8, round(2.5 / 25.4 * layout.dpi))
                try:
                    font = ImageFont.truetype("arial.ttf", font_size)
                except OSError:
                    font = ImageFont.load_default()
                pad = tick_w * 3
                if has_right:
                    x = layout.tile_w_px - layout.overlap_px + pad
                    y = layout.tile_h_px // 2
                else:
                    x = layout.tile_w_px // 2
                    y = layout.tile_h_px - layout.overlap_px + pad
                draw.text((x, y), label, fill=(160, 160, 160), font=font)

        images.append(tile_img)

    return images


def save_pdf(tiles: list[Image.Image], layout: Layout, path: str | Path) -> None:
    """Save tiles as a multi-page PDF; each page is the full physical sheet."""
    path = Path(path)
    sheet = layout.sheet
    page_w_px = round(sheet.width_mm / 25.4 * layout.dpi)
    page_h_px = round(sheet.height_mm / 25.4 * layout.dpi)
    left_px = round(sheet.left_mm / 25.4 * layout.dpi)
    top_px = round(sheet.top_mm / 25.4 * layout.dpi)

    pages: list[Image.Image] = []
    for tile_img, tile in zip(tiles, layout.tiles):
        page = Image.new("RGB", (page_w_px, page_h_px), (255, 255, 255))
        page.paste(tile_img, (left_px, top_px))
        pages.append(page)

    if not pages:
        return

    first = pages[0]
    first.save(
        path,
        save_all=True,
        append_images=pages[1:],
        resolution=layout.dpi,
    )


def save_pngs(
    tiles: list[Image.Image],
    layout: Layout,
    folder: str | Path,
    stem: str,
) -> list[Path]:
    """Save tiles as individual PNGs with DPI metadata.

    Returns list of written paths.
    """
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    for tile_img, tile in zip(tiles, layout.tiles):
        name = f"{stem}_r{tile.row + 1}_c{tile.col + 1}.png"
        p = folder / name
        dpi_tuple = (layout.dpi, layout.dpi)
        tile_img.save(p, dpi=dpi_tuple)
        paths.append(p)

    return paths
