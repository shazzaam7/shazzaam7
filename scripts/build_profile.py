#!/usr/bin/env python3
"""Build the profile README and its images from assets/profile/profile.json.

    python3 scripts/build_profile.py

Writes README.md plus the hero, badge, section-title and stack SVGs in assets/profile/.
The stats images (stats.svg, top-langs.svg) are made by the stats workflow instead.
Downloaded icons are cached in scripts/.icon-cache/ (git-ignored).
Needs Pillow:  pip install pillow
"""

import base64
import html
import io
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = ROOT / "assets" / "profile"
CACHE = HERE / ".icon-cache"
DEVICON = (
    "https://raw.githubusercontent.com/devicons/devicon/master/icons/{n}/{n}-{v}.svg"
)
SIMPLE_ICONS = "https://raw.githubusercontent.com/simple-icons/simple-icons/develop/icons/{slug}.svg"
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
W = 750  # width of the wide SVGs, sized to the GitHub README column

# Devicons with their own dark shapes: recolouring them would flatten them in dark mode.
KEEP_COLOURS = {"rider", "clion", "nextjs"}

# Lucide (ISC licence) icon paths on a 24x24 grid, used for the section titles.
LUCIDE = {
    "folder": '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
    "layers": '<path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/>'
    '<path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/><path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/>',
}

# Colours for each theme. Change these to restyle every image at once.
THEMES = {
    "light": dict(
        bg="#fafafa",
        border="#e4e4e7",
        tile="#ffffff",
        fg="#18181b",
        muted="#71717a",
        accent="#b45309",
        glow="#fbbf24",
        glow_op="0.22",
        chip="#ffffff",
    ),
    "dark": dict(
        bg="#09090b",
        border="#27272a",
        tile="#18181b",
        fg="#fafafa",
        muted="#a1a1aa",
        accent="#fbbf24",
        glow="#fbbf24",
        glow_op="0.14",
        chip="#18181b",
    ),
}


def esc(s):
    return html.escape(str(s), quote=True)


def emit(name, text):
    (OUT / name).write_text(text, encoding="utf-8")
    print("wrote", (OUT / name).relative_to(ROOT))


def svg(w, h, label, defs, body):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        f'role="img" aria-label="{esc(label)}"><title>{esc(label)}</title><defs>{defs}</defs>{body}</svg>\n'
    )


def svg_data_uri(text):
    return "data:image/svg+xml;base64," + base64.b64encode(text.encode()).decode()


def set_root_fill(s, colour):
    # Simple Icons paths have no fill of their own, so the root fill sets the colour for a theme.
    return re.sub(r"<svg\b", f'<svg fill="{colour}"', s, count=1)


def strip_root_size(s):
    # Drop width/height from the root <svg> tag so the viewBox alone sets the aspect ratio.
    end = s.index(">")
    return re.sub(r'\s(?:width|height)="[^"]*"', "", s[:end]) + s[end:]


# ---------- icons ----------


def devicon(spec):
    """Return the SVG text for a devicon spec, downloading it once into the cache.

    spec is "name" (tries original, then plain) or "name:variant", e.g. "go:original-wordmark"
    for icons/go/go-original-wordmark.svg. Browse variants at https://devicon.dev.
    """
    name, _, variant = spec.partition(":")
    CACHE.mkdir(exist_ok=True)
    cached = CACHE / (f"{name}-{variant}.svg" if variant else f"{name}.svg")
    if not cached.exists():
        for v in [variant] if variant else ["original", "plain"]:
            try:
                with urllib.request.urlopen(
                    DEVICON.format(n=name, v=v), timeout=30
                ) as r:
                    cached.write_bytes(r.read())
                break
            except OSError:
                continue
        else:
            sys.exit(f'no devicon for "{spec}" (browse https://devicon.dev)')
    return cached.read_text(encoding="utf-8")


def simple_icon(slug):
    """Return the Simple Icons SVG for a slug, downloading it once. None if it can't be fetched."""
    CACHE.mkdir(exist_ok=True)
    cached = CACHE / f"si-{slug}.svg"
    if not cached.exists():
        try:
            with urllib.request.urlopen(
                SIMPLE_ICONS.format(slug=slug), timeout=30
            ) as r:
                cached.write_bytes(r.read())
        except OSError:
            return None
    return cached.read_text(encoding="utf-8")


def near_black(colour):
    h = colour.lstrip("#")
    if len(h) == 3:
        h = "".join(x * 2 for x in h)
    if len(h) != 6:
        return False
    r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))
    return max(r, g, b) < 0.35 and max(r, g, b) - min(r, g, b) < 0.12


def lift_dark_fills(s):
    """Lighten near-black fills so they stay visible on the dark background."""

    def lift(m):
        c = m.group(2)
        return m.group(1) + ("#e4e4e7" if c == "black" or near_black(c) else c)

    s = re.sub(r'(fill=["\']|fill:\s*)(#[0-9a-fA-F]{3,6}|black)', lift, s)
    if not re.search(r"<svg\b[^>]*\sfill=", s):  # unfilled paths default to black
        s = s.replace("<svg", '<svg fill="#e4e4e7"', 1)
    return s


def provider_svg(provider, spec, theme):
    """Return the raw SVG text for an icon from the named provider."""
    if provider == "devicon":
        s = devicon(spec)
        if theme == "dark" and spec.partition(":")[0] not in KEEP_COLOURS:
            s = lift_dark_fills(s)
        return s
    if provider == "simpleicons":
        s = simple_icon(spec)
        if s is None:
            sys.exit(f'no Simple Icons logo "{spec}" (browse https://simpleicons.org)')
        return set_root_fill(s, THEMES[theme]["fg"])
    if provider == "file":
        # A local SVG, relative to the repo root, e.g. "file/assets/profile/icons/avalonia.svg".
        path = ROOT / spec
        if not path.is_file():
            sys.exit(f'no icon file "{spec}" (paths are relative to the repo root)')
        return path.read_text(encoding="utf-8")
    sys.exit(
        f'unknown icon provider "{provider}" (use "devicon", "simpleicons" or "file")'
    )


def icon_uri(spec, theme, vb=None):
    """Return (data URI, aspect ratio) for an icon.

    spec is a devicon name ("name" or "name:variant"), a simple-icons slug, or a path to a local
    SVG. Prefix it with a provider to choose the source, e.g. "simpleicons/nodedotjs",
    "devicon/csharp" or "file/assets/profile/icons/avalonia.svg". vb overrides the viewBox
    to crop the artwork.
    """
    provider = "devicon"
    if "/" in spec:
        provider, spec = spec.split("/", 1)
    s = strip_root_size(provider_svg(provider, spec, theme))
    if vb:
        s = re.sub(r'viewBox="[^"]*"', f'viewBox="{vb}"', s, count=1)
    x, y, w, h = (
        float(n)
        for n in re.split(
            r"[\s,]+", re.search(r'viewBox="([^"]*)"', s).group(1).strip()
        )
    )
    return svg_data_uri(s), w / h


def avatar_uri(path):
    try:
        from PIL import Image
    except ImportError:
        sys.exit("Pillow is needed: pip install pillow")
    im = Image.open(ROOT / path).convert("RGBA").resize((360, 360), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


# ---------- SVG builders ----------


def hero_svg(h, theme, avatar):
    c, H = THEMES[theme], 240
    x, chips = 236, []
    for t in h["chips"]:
        w = len(t) * 7.4 + 26
        chips.append(
            f'<rect x="{x + .5:.1f}" y="182.5" width="{w:.1f}" height="24" rx="12" fill="{c["chip"]}" stroke="{c["border"]}"/>'
            f'<text x="{x + w / 2:.1f}" y="198" text-anchor="middle" font-family="{FONT}" font-size="12" '
            f'font-weight="600" fill="{c["fg"]}">{esc(t)}</text>'
        )
        x += w + 8
    defs = (
        f'<radialGradient id="g" cx="112" cy="120" r="200" gradientUnits="userSpaceOnUse">'
        f'<stop offset="0" stop-color="{c["glow"]}" stop-opacity="{c["glow_op"]}"/>'
        f'<stop offset="1" stop-color="{c["glow"]}" stop-opacity="0"/></radialGradient>'
        f'<clipPath id="card"><rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="16"/></clipPath>'
        '<clipPath id="av"><rect x="32" y="40" width="160" height="160" rx="24"/></clipPath>'
    )
    body = (
        f'<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="16" fill="{c["bg"]}"/>'
        f'<g clip-path="url(#card)"><rect width="{W}" height="{H}" fill="url(#g)"/></g>'
        f'<image x="32" y="40" width="160" height="160" href="{avatar}" clip-path="url(#av)"/>'
        f'<rect x="32.5" y="40.5" width="159" height="159" rx="24" fill="none" stroke="{c["border"]}"/>'
        f'<line x1="212" y1="40" x2="212" y2="200" stroke="{c["border"]}"/>'
        f'<text x="236" y="68" font-family="{FONT}" font-size="12" font-weight="700" letter-spacing="1.8" '
        f'fill="{c["accent"]}">{esc(h["eyebrow"])}</text>'
        f'<text x="234" y="116" font-family="{FONT}" font-size="50" font-weight="800" letter-spacing="-1" '
        f'fill="{c["fg"]}">{esc(h["name"])}</text>'
        f'<text x="236" y="146" font-family="{FONT}" font-size="17" font-weight="600" '
        f'fill="{c["fg"]}">{esc(h["headline"])}</text>'
        f'<text x="236" y="168" font-family="{FONT}" font-size="14" fill="{c["muted"]}">{esc(h["detail"])}</text>'
        + "".join(chips)
        + f'<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="16" fill="none" stroke="{c["border"]}"/>'
    )
    return svg(W, H, f'{h["name"]}: {h["headline"]}', defs, body)


def title_svg(title, subtitle, icon, theme):
    c, H = THEMES[theme], 100
    if icon not in LUCIDE:
        sys.exit(f'unknown icon "{icon}", choose from: {", ".join(LUCIDE)}')
    body = (
        f'<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="12" fill="{c["bg"]}"/>'
        f'<rect x="22" y="22" width="56" height="56" rx="12" fill="{c["tile"]}" stroke="{c["border"]}"/>'
        f'<g transform="translate(36 36) scale(1.1667)" fill="none" stroke="{c["fg"]}" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round">{LUCIDE[icon]}</g>'
        f'<line x1="100" y1="22" x2="100" y2="78" stroke="{c["border"]}"/>'
        f'<text x="124" y="49" font-family="{FONT}" font-size="28" font-weight="700" fill="{c["fg"]}">{esc(title)}</text>'
        f'<text x="124" y="74" font-family="{FONT}" font-size="15" fill="{c["muted"]}">{esc(subtitle)}</text>'
        f'<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="12" fill="none" stroke="{c["border"]}"/>'
    )
    return svg(W, H, title, "", body)


def stack_summary(groups):
    return "; ".join(
        f'{g["label"]}: ' + ", ".join(ic[0] for ic in g["icons"]) for g in groups
    )


def stack_svg(groups, theme):
    c = THEMES[theme]
    CW, GAP, PAD = 369, 12, 16  # card width, gap between cards, inner padding
    TILE, IG, ICON = 34, 6, 22  # icon tile size, gap between tiles, icon size
    HEAD = 96  # card height with one row of icons
    ROW = TILE + IG  # vertical distance between icon rows inside a card
    limit = CW - PAD
    laid = []  # (group, tiles markup, card height)
    for g in groups:
        tiles, tx, row = [], PAD, 0
        for alt, spec, *crop in g[
            "icons"
        ]:  # optional third item: a viewBox to crop the artwork
            uri, aspect = icon_uri(spec, theme, crop[0] if crop else None)
            iw = min(
                ICON * aspect, 40
            )  # wide wordmarks get a wider tile, capped to fit the card
            ih = iw / aspect
            tile_w = max(TILE, iw + 12)
            if (
                tx > PAD and tx + tile_w - IG > limit
            ):  # wrap onto a new row inside the card
                tx, row = PAD, row + 1
            y = 44.5 + row * ROW
            tiles.append(
                f"<g><title>{esc(alt)}</title>"
                f'<rect x="{tx + .5}" y="{y}" width="{tile_w - 1}" height="{TILE - 1}" rx="9" '
                f'fill="{c["tile"]}" stroke="{c["border"]}"/>'
                f'<image x="{tx + (tile_w - iw) / 2:.1f}" y="{y + 5.5 + (ICON - ih) / 2:.1f}" '
                f'width="{iw:.1f}" height="{ih:.1f}" href="{uri}"/></g>'
            )
            tx += tile_w + IG
        laid.append((g, "".join(tiles), HEAD + row * ROW))

    # Two cards per grid row; each grid row is as tall as its tallest card.
    row_heights = [
        max(h for _, _, h in laid[r : r + 2]) for r in range(0, len(laid), 2)
    ]
    H = sum(row_heights) + (len(row_heights) - 1) * GAP
    cards, y0 = [], 0
    for r, rh in enumerate(row_heights):
        for col in range(2):
            i = 2 * r + col
            if i >= len(laid):
                break
            g, tiles, h = laid[i]
            x, label = col * (CW + GAP), g["label"]
            cards.append(
                f'<g transform="translate({x} {y0})">'
                f'<rect x="0.5" y="0.5" width="{CW - 1}" height="{h - 1}" rx="12" fill="{c["bg"]}"/>'
                f'<text x="{PAD}" y="30" font-family="{FONT}" font-size="11" font-weight="700" letter-spacing="1.4" '
                f'fill="{c["muted"]}">{esc(label.upper())}</text>'
                f'<line x1="{PAD + len(label) * 8.2 + 8:.0f}" y1="26.5" x2="{CW - PAD}" y2="26.5" stroke="{c["border"]}"/>'
                + tiles
                + f'<rect x="0.5" y="0.5" width="{CW - 1}" height="{h - 1}" rx="12" fill="none" stroke="{c["border"]}"/>'
                "</g>"
            )
        y0 += rh + GAP
    return svg(W, H, "Tech stack. " + stack_summary(groups), "", "".join(cards))


# ---------- badges ----------


def badge_svg(text, logo, theme):
    """Pill in the same chip style as the hero tags, so badges and images share one look."""
    c, H, ICON = THEMES[theme], 34, 16
    logo_uri = None
    if logo:
        raw = simple_icon(logo)
        if raw is None:
            print(
                f'warning: no simple-icons logo "{logo}", that badge is drawn without one'
            )
        else:
            logo_uri = svg_data_uri(set_root_fill(raw, c["fg"]))
    x_text = 12 + ICON + 7 if logo_uri else 14
    w = x_text + len(text) * 7.6 + 14
    img = (
        f'<image x="12" y="{(H - ICON) / 2}" width="{ICON}" height="{ICON}" href="{logo_uri}"/>'
        if logo_uri
        else ""
    )
    body = (
        f'<rect x="0.5" y="0.5" width="{w - 1:.1f}" height="{H - 1}" rx="{H / 2 - 0.5}" '
        f'fill="{c["chip"]}" stroke="{c["border"]}"/>'
        + img
        + f'<text x="{x_text}" y="{H / 2 + 4.5}" font-family="{FONT}" font-size="13" font-weight="600" '
        f'fill="{c["fg"]}">{esc(text)}</text>'
    )
    return svg(round(w), H, text, "", body)


# ---------- README ----------


def header_url(title, subtitle, logo, theme):
    q = urllib.parse.urlencode(
        {"title": title, "subtitle": subtitle, "logo": logo, "mode": theme},
        quote_via=urllib.parse.quote_plus,
    )
    return f"https://shieldcn.dev/header/surface.svg?{q}"


def pin_url(user, repo, theme):
    return (
        "https://github-stats-extended.vercel.app/api/pin?"
        f"username={user}&repo={repo}&show_owner=true&border_radius=12"
        f"&description_lines_count=2&card_width=400&theme={theme}"
    )


def pic(dark, light, alt, full=True):
    width = ' width="100%"' if full else ""
    return (
        f'<picture>\n    <source media="(prefers-color-scheme: dark)" srcset="{esc(dark)}">\n'
        f'    <img{width} alt="{esc(alt)}" src="{esc(light)}">\n  </picture>'
    )


def readme(cfg):
    P = "assets/profile/"
    hero = cfg["hero"]
    per = cfg.get("projects_per_row", 2)

    def centred(inner):
        return f'<p align="center">\n  {inner}\n</p>'

    def title(key):
        s = cfg["sections"][key]
        return centred(
            pic(f"{P}title-{key}-dark.svg", f"{P}title-{key}-light.svg", s["title"])
        )

    def card(repo):
        dark, light = pin_url(cfg["user"], repo, "dark"), pin_url(
            cfg["user"], repo, "default"
        )
        return f'<a href="https://github.com/{repo}">{pic(dark, light, repo, full=False)}</a>'

    def badge(i, b):
        dark, light = P + f"badge-{i}-dark.svg", P + f"badge-{i}-light.svg"
        return (
            f'<a href="{esc(b["href"])}">{pic(dark, light, b["alt"], full=False)}</a>'
        )

    hero_alt = f'{hero["name"]}. {hero["headline"]} {hero["detail"]}'
    parts = [
        "<!-- Generated by scripts/build_profile.py from assets/profile/profile.json. "
        "Edit those files and re-run the script; changes made here are overwritten. -->",
        centred(pic(P + "hero-dark.svg", P + "hero-light.svg", hero_alt)),
        centred("\n  ".join(badge(i, b) for i, b in enumerate(cfg["badges"]))),
        title("stack"),
        centred(
            pic(
                P + "stack-dark.svg",
                P + "stack-light.svg",
                "Tech stack. " + stack_summary(cfg["stack"]),
            )
        ),
        title("projects"),
    ]
    for p in cfg["projects"]:
        dark = header_url(p["title"], p["subtitle"], p["logo"], "dark")
        light = header_url(p["title"], p["subtitle"], p["logo"], "light")
        # The banner links to "href" if set (e.g. an official site), otherwise to the repo's GitHub org.
        href = p.get("href") or f"https://github.com/{p['repo'].split('/')[0]}"
        parts.append(
            centred(
                f'<a href="{esc(href)}">{pic(dark, light, p["title"], full=False)}</a>'
            )
        )
        parts.append(centred(card(p["repo"])))
        side = p.get("side", [])
        for i in range(0, len(side), per):
            parts.append(centred("\n  ".join(card(r) for r in side[i : i + per])))
    return "\n\n".join(parts) + "\n"


def main():
    cfg = json.loads(
        (ROOT / "assets" / "profile" / "profile.json").read_text(encoding="utf-8")
    )
    avatar = avatar_uri(cfg["avatar"])
    OUT.mkdir(parents=True, exist_ok=True)
    for theme in THEMES:
        emit(f"hero-{theme}.svg", hero_svg(cfg["hero"], theme, avatar))
        emit(f"stack-{theme}.svg", stack_svg(cfg["stack"], theme))
        for i, b in enumerate(cfg["badges"]):
            emit(f"badge-{i}-{theme}.svg", badge_svg(b["text"], b.get("logo"), theme))
        for key, s in cfg["sections"].items():
            emit(
                f"title-{key}-{theme}.svg",
                title_svg(s["title"], s["subtitle"], s["icon"], theme),
            )
    (ROOT / "README.md").write_text(readme(cfg), encoding="utf-8")
    print("wrote README.md")


if __name__ == "__main__":
    main()
