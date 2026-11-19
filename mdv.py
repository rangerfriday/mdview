import sys
import solaros
from solaros import gfx

try:
    from solaros import image as simage
    HAS_IMAGE = True
except ImportError:
    HAS_IMAGE = False

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp")

# Font presets: (name, body_font, bold_font, mono_font, h1_font, h2_font, h3_font, char_w, line_h, h1_h, h2_h, h3_h)
FONT_PRESETS = [
    (
        "Small",
        gfx.FONT_SMALL,
        gfx.FONT_BOLD_12,
        gfx.FONT_MONO_12,
        gfx.FONT_BOLD_16,
        gfx.FONT_BOLD_14,
        gfx.FONT_BOLD_12,
        6, 13, 22, 18, 15,
    ),
    (
        "Medium",
        gfx.FONT_MONO_14,
        gfx.FONT_BOLD_14,
        gfx.FONT_MONO_14,
        gfx.FONT_BOLD_18,
        gfx.FONT_BOLD_16,
        gfx.FONT_BOLD_14,
        8, 17, 25, 21, 18,
    ),
    (
        "Large",
        gfx.FONT_MONO_16,
        gfx.FONT_BOLD_16,
        gfx.FONT_MONO_16,
        gfx.FONT_BOLD_20,
        gfx.FONT_BOLD_18,
        gfx.FONT_BOLD_16,
        9, 20, 28, 24, 21,
    ),
]


def path_dirname(path):
    idx = path.rfind("/")
    if idx < 0:
        return "."
    if idx == 0:
        return "/"
    return path[:idx]


def path_basename(path):
    idx = path.rfind("/")
    if idx < 0:
        return path
    return path[idx + 1:]


def path_norm(path):
    if not path:
        return "."
    is_abs = path.startswith("/")
    parts = []
    for p in path.split("/"):
        if not p or p == ".":
            continue
        if p == "..":
            if parts and parts[-1] != "..":
                parts.pop()
            elif not is_abs:
                parts.append("..")
        else:
            parts.append(p)
    res = "/".join(parts)
    if is_abs:
        return "/" + res
    return res if res else "."


def path_join(base, target):
    if not target:
        return path_norm(base)
    if target.startswith("/"):
        return path_norm(target)
    if not base or base == ".":
        return path_norm(target)
    if base == "/":
        return path_norm("/" + target)
    return path_norm(base + "/" + target)


def path_exists(path):
    try:
        f = open(path, "rb")
        f.close()
        return True
    except OSError:
        return False


def is_image_path(path):
    low = path.lower()
    for ext in IMAGE_EXTS:
        if low.endswith(ext):
            return True
    return False


def resolve_target(base_dir, target, is_wiki=False):
    target = target.strip()
    if "#" in target:
        target = target.split("#", 1)[0].strip()
    if not target:
        return ""

    candidates = []
    if target.startswith("/"):
        candidates.append(path_norm(target))
    else:
        candidates.append(path_join(base_dir, target))
        candidates.append(path_norm(target))

    expanded = []
    for c in candidates:
        expanded.append(c)
        if is_wiki and not is_image_path(c) and not c.lower().endswith(".md"):
            expanded.append(c + ".md")

    for c in expanded:
        if path_exists(c):
            return c

    return expanded[0] if expanded else target


def read_text_file(path):
    try:
        with open(path, "r") as f:
            return f.read()
    except Exception as e:
        return "# Error Opening File\n\nCould not read `" + path + "`: " + str(e)


def parse_inline(text, base_dir):
    """
    Tokenize inline markdown into segments:
    (kind, text, target)
    kinds: 'text', 'bold', 'code', 'link'
    """
    tokens = []
    n = len(text)
    i = 0
    buf = []

    def flush_buf():
        if buf:
            tokens.append(("text", "".join(buf), None))
            del buf[:]

    while i < n:
        # Escaped character
        if text[i] == "\\" and i + 1 < n:
            buf.append(text[i + 1])
            i += 2
            continue

        # Obsidian wiki link [[target]] or [[target|alias]]
        if text.startswith("[[", i):
            end = text.find("]]", i + 2)
            if end != -1:
                flush_buf()
                inner = text[i + 2:end]
                if "|" in inner:
                    tgt, label = inner.split("|", 1)
                else:
                    tgt, label = inner, inner
                resolved = resolve_target(base_dir, tgt, is_wiki=True)
                tokens.append(("link", label.strip(), resolved))
                i = end + 2
                continue

        # Standard markdown link [label](target)
        if text[i] == "[":
            close_b = text.find("]", i + 1)
            if close_b != -1 and close_b + 1 < n and text[close_b + 1] == "(":
                close_p = text.find(")", close_b + 2)
                if close_p != -1:
                    flush_buf()
                    label = text[i + 1:close_b]
                    tgt = text[close_b + 2:close_p]
                    resolved = resolve_target(base_dir, tgt, is_wiki=False)
                    tokens.append(("link", label, resolved))
                    i = close_p + 1
                    continue

        # Bold **text**
        if text.startswith("**", i):
            end = text.find("**", i + 2)
            if end != -1:
                flush_buf()
                tokens.append(("bold", text[i + 2:end], None))
                i = end + 2
                continue

        # Inline code `code`
        if text[i] == "`":
            end = text.find("`", i + 1)
            if end != -1:
                flush_buf()
                tokens.append(("code", text[i + 1:end], None))
                i = end + 1
                continue

        buf.append(text[i])
        i += 1

    flush_buf()
    return tokens


def expand_transclusions(raw_text, base_dir, visited=None, depth=0):
    if visited is None:
        visited = set()
    if depth > 5:
        return raw_text

    out_lines = []
    for line in raw_text.split("\n"):
        s = line.strip()
        if s.startswith("![[") and s.endswith("]]") and len(s) > 5:
            inner = s[3:-2].strip()
            target_part = inner.split("|", 1)[0].strip()
            resolved = resolve_target(base_dir, target_part, is_wiki=True)
            if is_image_path(resolved):
                out_lines.append(line)
            else:
                if resolved in visited:
                    out_lines.append("> *[Circular include skipped: " + target_part + "]*")
                elif path_exists(resolved):
                    visited.add(resolved)
                    sub_raw = read_text_file(resolved)
                    sub_dir = path_dirname(resolved)
                    out_lines.append(expand_transclusions(sub_raw, sub_dir, visited, depth + 1))
                else:
                    out_lines.append("> *[Missing include: " + target_part + "]*")
        else:
            out_lines.append(line)
    return "\n".join(out_lines)


def parse_markdown_blocks(raw_text, base_dir):
    """
    Parse markdown text into high-level blocks:
    - ('header', level, tokens)
    - ('code', lang, code_lines)
    - ('table', rows_of_cells_tokens)
    - ('image', path, req_width, caption)
    - ('hr', None)
    - ('paragraph', tokens)
    - ('blank', None)
    """
    expanded = expand_transclusions(raw_text, base_dir)
    lines = expanded.split("\n")
    blocks = []
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        stripped = line.strip()

        # Blank line
        if not stripped:
            blocks.append(("blank", None))
            i += 1
            continue

        # Fenced code block
        if stripped.startswith("```"):
            lang = stripped[3:].strip()
            code_lines = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            if i < n:
                i += 1
            blocks.append(("code", lang, code_lines))
            continue

        # Horizontal rule
        if stripped in ("---", "***", "___"):
            blocks.append(("hr", None))
            i += 1
            continue

        # Headers
        if stripped.startswith("#"):
            lvl = 0
            while lvl < len(stripped) and lvl < 3 and stripped[lvl] == "#":
                lvl += 1
            if lvl < len(stripped) and stripped[lvl] == " ":
                content = stripped[lvl + 1:].strip()
                blocks.append(("header", lvl, parse_inline(content, base_dir)))
                i += 1
                continue

        # Standalone Obsidian image ![[img.png]] or ![[img.png|120]]
        if stripped.startswith("![[") and stripped.endswith("]]"):
            inner = stripped[3:-2].strip()
            req_w = None
            if "|" in inner:
                tgt, meta = inner.split("|", 1)
                meta = meta.strip()
                if meta.isdigit():
                    req_w = int(meta)
            else:
                tgt = inner
            resolved = resolve_target(base_dir, tgt, is_wiki=True)
            blocks.append(("image", resolved, req_w, path_basename(tgt)))
            i += 1
            continue

        # Standalone standard markdown image ![alt](path)
        if stripped.startswith("!["):
            cb = stripped.find("]")
            if cb != -1 and cb + 1 < len(stripped) and stripped[cb + 1] == "(":
                cp = stripped.find(")", cb + 2)
                if cp == len(stripped) - 1:
                    alt = stripped[2:cb]
                    tgt = stripped[cb + 2:cp]
                    resolved = resolve_target(base_dir, tgt, is_wiki=False)
                    blocks.append(("image", resolved, None, alt))
                    i += 1
                    continue

        # Markdown Table
        if "|" in stripped and i + 1 < n:
            nxt = lines[i + 1].strip()
            if "|" in nxt and "-" in nxt:
                is_sep = True
                for ch in nxt:
                    if ch not in "|-: \t":
                        is_sep = False
                        break
                if is_sep:
                    table_rows = []
                    # Header row
                    hdr_cells = [c.strip() for c in stripped.strip("|").split("|")]
                    table_rows.append([parse_inline(c, base_dir) for c in hdr_cells])
                    i += 2
                    while i < n and "|" in lines[i].strip() and lines[i].strip():
                        row_str = lines[i].strip().strip("|")
                        cells = [c.strip() for c in row_str.split("|")]
                        table_rows.append([parse_inline(c, base_dir) for c in cells])
                        i += 1
                    blocks.append(("table", table_rows))
                    continue

        # Bullet list item
        if stripped.startswith("- ") or stripped.startswith("* "):
            item_tokens = [("bold", "* ", None)] + parse_inline(stripped[2:], base_dir)
            blocks.append(("paragraph", item_tokens))
            i += 1
            continue

        # Blockquote
        if stripped.startswith("> "):
            q_tokens = [("bold", "| ", None)] + parse_inline(stripped[2:], base_dir)
            blocks.append(("paragraph", q_tokens))
            i += 1
            continue

        # Regular paragraph
        para_lines = [stripped]
        i += 1
        while i < n:
            ns = lines[i].strip()
            if (
                not ns
                or ns.startswith("#")
                or ns.startswith("```")
                or ns.startswith("![")
                or ns.startswith("- ")
                or ns.startswith("* ")
                or ns.startswith("> ")
                or ns in ("---", "***", "___")
            ):
                break
            if "|" in ns and i + 1 < n and "-" in lines[i + 1]:
                break
            para_lines.append(ns)
            i += 1
        blocks.append(("paragraph", parse_inline(" ".join(para_lines), base_dir)))

    return blocks


def wrap_tokens(tokens, max_w, char_w, link_registry):
    """
    Wrap inline tokens into visual lines of segments:
    Each line is a list of (kind, text, x_offset, width, link_idx)
    """
    lines = []
    cur_line = []
    cur_x = 0

    for kind, text, target in tokens:
        link_idx = None
        if kind == "link":
            link_idx = len(link_registry)
            link_registry.append((text, target))

        # Split into words while preserving spaces
        words = []
        w_buf = []
        for ch in text:
            if ch == " ":
                if w_buf:
                    words.append("".join(w_buf))
                    del w_buf[:]
                words.append(" ")
            else:
                w_buf.append(ch)
        if w_buf:
            words.append("".join(w_buf))

        for word in words:
            ww = len(word) * char_w
            if cur_x > 0 and cur_x + ww > max_w and word != " ":
                lines.append(cur_line)
                cur_line = []
                cur_x = 0
            if cur_x == 0 and word == " ":
                continue

            # Break extra long single words if wider than screen
            if ww > max_w and len(word) > 1:
                max_chars = max(1, max_w // char_w)
                pos = 0
                while pos < len(word):
                    chunk = word[pos:pos + max_chars]
                    cw = len(chunk) * char_w
                    if cur_x > 0 and cur_x + cw > max_w:
                        lines.append(cur_line)
                        cur_line = []
                        cur_x = 0
                    cur_line.append((kind, chunk, cur_x, cw, link_idx))
                    cur_x += cw
                    pos += max_chars
            else:
                if cur_line and cur_line[-1][0] == kind and cur_line[-1][4] == link_idx:
                    pk, pt, px, pw, pl = cur_line[-1]
                    cur_line[-1] = (pk, pt + word, px, pw + ww, pl)
                else:
                    cur_line.append((kind, word, cur_x, ww, link_idx))
                cur_x += ww

    if cur_line:
        lines.append(cur_line)
    return lines


def tokens_plain_text(tokens):
    return "".join(t[1] for t in tokens)


class MarkdownViewer:
    def __init__(self, initial_file):
        self.history = []
        self.current_file = path_norm(initial_file)
        self.preset_idx = 0
        self.scroll_y = 0
        self.items = []
        self.links = []
        self.selected_link = -1
        self.content_height = 0
        self.image_handles = []

        # Search state
        self.search_mode = False
        self.search_query = ""
        self.matches = []
        self.match_idx = -1

    def close_images(self):
        if HAS_IMAGE:
            for h in self.image_handles:
                try:
                    simage.close(h)
                except Exception:
                    pass
        del self.image_handles[:]

    def load_file(self, filepath, push_history=True):
        if push_history and self.current_file and filepath != self.current_file:
            self.history.append((self.current_file, self.scroll_y))
        self.current_file = path_norm(filepath)
        self.scroll_y = 0
        self.selected_link = -1
        self.matches = []
        self.match_idx = -1
        self.rebuild_layout()
        if self.search_query:
            self.run_search(jump=False)

    def go_back(self):
        if self.history:
            prev_file, prev_scroll = self.history.pop()
            self.current_file = prev_file
            self.selected_link = -1
            self.rebuild_layout()
            self.scroll_y = min(prev_scroll, max(0, self.content_height - self.view_height()))
            if self.search_query:
                self.run_search(jump=False)

    def view_height(self):
        return max(40, gfx.height() - self.header_bar_h())

    def header_bar_h(self):
        return 18

    def rebuild_layout(self):
        self.close_images()
        self.items = []
        self.links = []

        w, _ = gfx.size()
        margin = 6
        usable_w = max(60, w - margin * 2)

        preset = FONT_PRESETS[self.preset_idx]
        _, f_body, f_bold, f_mono, f_h1, f_h2, f_h3, cw, lh, h1_h, h2_h, h3_h = preset

        raw = read_text_file(self.current_file)
        base_dir = path_dirname(self.current_file)
        blocks = parse_markdown_blocks(raw, base_dir)

        y = 4
        for blk in blocks:
            btype = blk[0]

            if btype == "blank":
                y += lh // 2

            elif btype == "hr":
                self.items.append(("hr", y + 4, 8, margin, usable_w, None))
                y += 10

            elif btype == "header":
                lvl = blk[1]
                tokens = blk[2]
                if lvl == 1:
                    hf, h_lh, h_cw = f_h1, h1_h, cw + 2
                elif lvl == 2:
                    hf, h_lh, h_cw = f_h2, h2_h, cw + 1
                else:
                    hf, h_lh, h_cw = f_h3, h3_h, cw + 1

                y += 3
                wrapped = wrap_tokens(tokens, usable_w, h_cw, self.links)
                for wline in wrapped:
                    plain = "".join(seg[1] for seg in wline)
                    self.items.append(("header_line", y, h_lh, margin, hf, (wline, plain)))
                    y += h_lh
                if lvl == 1:
                    self.items.append(("hr", y + 1, 3, margin, usable_w, None))
                    y += 4

            elif btype == "paragraph":
                tokens = blk[1]
                wrapped = wrap_tokens(tokens, usable_w, cw, self.links)
                for wline in wrapped:
                    plain = "".join(seg[1] for seg in wline)
                    self.items.append(("text_line", y, lh, margin, cw, (wline, plain)))
                    y += lh

            elif btype == "code":
                lang = blk[1]
                code_lines = blk[2]
                if not code_lines:
                    code_lines = [""]
                code_cw = max(5, cw - 1)
                code_lh = max(12, lh - 2)
                max_chars = max(10, (usable_w - 8) // code_cw)

                wrapped_code = []
                for cl in code_lines:
                    if not cl:
                        wrapped_code.append("")
                    else:
                        pos = 0
                        while pos < len(cl):
                            wrapped_code.append(cl[pos:pos + max_chars])
                            pos += max_chars

                box_h = len(wrapped_code) * code_lh + 6
                self.items.append(("code_box", y, box_h, margin, usable_w, (lang, wrapped_code, code_lh, code_cw)))
                y += box_h + 4

            elif btype == "table":
                rows = blk[1]
                num_cols = 0
                for r in rows:
                    if len(r) > num_cols:
                        num_cols = len(r)
                if num_cols == 0:
                    continue

                col_w = max(24, usable_w // num_cols)
                cell_cw = max(5, cw - 1)
                cell_lh = max(12, lh - 2)
                inner_w = max(10, col_w - 6)

                for r_idx, row in enumerate(rows):
                    wrapped_cells = []
                    max_lines = 1
                    for c_idx in range(num_cols):
                        ctoks = row[c_idx] if c_idx < len(row) else []
                        wlines = wrap_tokens(ctoks, inner_w, cell_cw, self.links)
                        if not wlines:
                            wlines = [[]]
                        if len(wlines) > max_lines:
                            max_lines = len(wlines)
                        wrapped_cells.append(wlines)

                    row_h = max_lines * cell_lh + 4
                    plain_row = " | ".join(
                        tokens_plain_text(row[c]) if c < len(row) else "" for c in range(num_cols)
                    )
                    self.items.append((
                        "table_row",
                        y,
                        row_h,
                        margin,
                        col_w,
                        (r_idx == 0, num_cols, wrapped_cells, cell_lh, cell_cw, plain_row),
                    ))
                    y += row_h
                y += 4

            elif btype == "image":
                img_path = blk[1]
                req_w = blk[2]
                caption = blk[3]
                drawn = False
                if HAS_IMAGE and path_exists(img_path):
                    try:
                        handle = simage.open(img_path)
                        self.image_handles.append(handle)
                        sw, sh = simage.size(handle)
                        if sw > 0 and sh > 0:
                            dw = req_w if (req_w and req_w > 0) else sw
                            if dw > usable_w:
                                dw = usable_w
                            dh = max(1, (sh * dw) // sw)
                            self.items.append(("image_item", y, dh + 4, margin, dw, (handle, dh, caption)))
                            y += dh + 6
                            drawn = True
                    except Exception:
                        drawn = False

                if not drawn:
                    placeholder = "[Image: " + caption + "]"
                    self.items.append(("image_missing", y, lh + 4, margin, usable_w, placeholder))
                    y += lh + 6

        self.content_height = max(y + 10, self.view_height())

    def run_search(self, jump=True):
        self.matches = []
        self.match_idx = -1
        q = self.search_query.lower().strip()
        if not q:
            return

        for idx, item in enumerate(self.items):
            itype = item[0]
            text_blob = ""
            if itype in ("text_line", "header_line"):
                text_blob = item[5][1]
            elif itype == "code_box":
                text_blob = "".join(item[5][1])
            elif itype == "table_row":
                text_blob = item[5][5]
            elif itype == "image_missing":
                text_blob = item[5]

            if q in text_blob.lower():
                self.matches.append(idx)

        if self.matches:
            self.match_idx = 0
            if jump:
                self.jump_to_match()

    def jump_to_match(self):
        if 0 <= self.match_idx < len(self.matches):
            item_idx = self.matches[self.match_idx]
            item_y = self.items[item_idx][1]
            vh = self.view_height()
            target_scroll = max(0, item_y - vh // 3)
            max_scroll = max(0, self.content_height - vh)
            self.scroll_y = min(target_scroll, max_scroll)

    def ensure_link_visible(self):
        if self.selected_link < 0 or self.selected_link >= len(self.links):
            return
        for item in self.items:
            itype = item[0]
            iy = item[1]
            ih = item[2]
            found = False
            if itype in ("text_line", "header_line"):
                for seg in item[5][0]:
                    if seg[4] == self.selected_link:
                        found = True
                        break
            elif itype == "table_row":
                for cell_lines in item[5][2]:
                    for wline in cell_lines:
                        for seg in wline:
                            if seg[4] == self.selected_link:
                                found = True
                                break
            if found:
                vh = self.view_height()
                if iy < self.scroll_y:
                    self.scroll_y = max(0, iy - 10)
                elif iy + ih > self.scroll_y + vh:
                    self.scroll_y = min(max(0, self.content_height - vh), iy + ih - vh + 10)
                break

    def draw_segments(self, wline, base_x, baseline_y, default_font, bold_font, mono_font, line_h, is_search_match):
        if is_search_match:
            gfx.color(gfx.LIGHT)
            total_w = 0
            for seg in wline:
                if seg[2] + seg[3] > total_w:
                    total_w = seg[2] + seg[3]
            if total_w > 0:
                gfx.fill_rect(base_x - 1, baseline_y - line_h + 3, total_w + 2, line_h)

        for kind, text, sx, sw, link_idx in wline:
            draw_x = base_x + sx
            if kind == "bold":
                gfx.font(bold_font)
                gfx.color(gfx.BLACK)
                gfx.text(draw_x, baseline_y, text)
            elif kind == "code":
                gfx.font(mono_font)
                gfx.color(gfx.LIGHT)
                gfx.fill_rect(draw_x, baseline_y - line_h + 4, sw, line_h - 1)
                gfx.color(gfx.BLACK)
                gfx.text(draw_x, baseline_y, text)
            elif kind == "link":
                gfx.font(bold_font)
                if link_idx == self.selected_link:
                    gfx.color(gfx.BLACK)
                    gfx.fill_rect(draw_x - 1, baseline_y - line_h + 3, sw + 2, line_h)
                    gfx.color(gfx.WHITE)
                    gfx.text(draw_x, baseline_y, text)
                else:
                    gfx.color(gfx.DARK)
                    gfx.text(draw_x, baseline_y, text)
                    gfx.line(draw_x, baseline_y + 2, draw_x + sw - 1, baseline_y + 2)
            else:
                gfx.font(default_font)
                gfx.color(gfx.BLACK)
                gfx.text(draw_x, baseline_y, text)

    def render(self):
        w, h = gfx.size()
        top_h = self.header_bar_h()
        vh = h - top_h

        gfx.clear(gfx.WHITE)

        preset = FONT_PRESETS[self.preset_idx]
        p_name, f_body, f_bold, f_mono, f_h1, f_h2, f_h3, cw, lh, h1_h, h2_h, h3_h = preset

        active_match_item = self.matches[self.match_idx] if (0 <= self.match_idx < len(self.matches)) else -1
        match_set = set(self.matches)

        for idx, item in enumerate(self.items):
            itype = item[0]
            iy = item[1]
            ih = item[2]
            sy = top_h + iy - self.scroll_y

            if sy + ih < top_h or sy > h:
                continue

            is_match = idx in match_set

            if itype == "hr":
                margin, usable_w = item[3], item[4]
                gfx.color(gfx.DARK)
                gfx.line(margin, sy + 2, margin + usable_w, sy + 2)

            elif itype == "header_line":
                margin, hf, payload = item[3], item[4], item[5]
                wline, _ = payload
                baseline = sy + ih - 4
                self.draw_segments(wline, margin, baseline, hf, hf, f_mono, ih, is_match)
                if idx == active_match_item:
                    gfx.color(gfx.BLACK)
                    gfx.rect(margin - 3, sy, w - margin * 2 + 6, ih)

            elif itype == "text_line":
                margin, _, payload = item[3], item[4], item[5]
                wline, _ = payload
                baseline = sy + ih - 3
                self.draw_segments(wline, margin, baseline, f_body, f_bold, f_mono, ih, is_match)
                if idx == active_match_item:
                    gfx.color(gfx.BLACK)
                    gfx.rect(margin - 3, sy, w - margin * 2 + 6, ih)

            elif itype == "code_box":
                margin, usable_w, payload = item[3], item[4], item[5]
                _, wrapped_code, code_lh, _ = payload
                gfx.color(gfx.LIGHT)
                gfx.fill_rect(margin, sy, usable_w, ih)
                gfx.color(gfx.DARK)
                gfx.rect(margin, sy, usable_w, ih)
                gfx.font(f_mono)
                gfx.color(gfx.BLACK)
                cy = sy + 3
                for cl in wrapped_code:
                    gfx.text(margin + 4, cy + code_lh - 3, cl)
                    cy += code_lh
                if idx == active_match_item:
                    gfx.color(gfx.BLACK)
                    gfx.rect(margin - 2, sy - 1, usable_w + 4, ih + 2)

            elif itype == "table_row":
                margin, col_w, payload = item[3], item[4], item[5]
                is_hdr, num_cols, wrapped_cells, cell_lh, _, _ = payload
                total_tw = col_w * num_cols
                if is_hdr:
                    gfx.color(gfx.LIGHT)
                    gfx.fill_rect(margin, sy, total_tw, ih)
                elif is_match:
                    gfx.color(gfx.LIGHT)
                    gfx.fill_rect(margin, sy, total_tw, ih)

                gfx.color(gfx.DARK)
                gfx.rect(margin, sy, total_tw, ih)
                for c_idx in range(num_cols):
                    cx = margin + c_idx * col_w
                    if c_idx > 0:
                        gfx.color(gfx.DARK)
                        gfx.line(cx, sy, cx, sy + ih)
                    cell_lines = wrapped_cells[c_idx]
                    ly = sy + 2
                    cell_font = f_bold if is_hdr else f_body
                    for wline in cell_lines:
                        self.draw_segments(wline, cx + 3, ly + cell_lh - 3, cell_font, f_bold, f_mono, cell_lh, False)
                        ly += cell_lh

                if idx == active_match_item:
                    gfx.color(gfx.BLACK)
                    gfx.rect(margin - 2, sy - 1, total_tw + 4, ih + 2)

            elif itype == "image_item":
                margin, dw, payload = item[3], item[4], item[5]
                handle, dh, _ = payload
                try:
                    simage.draw(handle, margin, sy + 2, dw, dh)
                except Exception:
                    gfx.color(gfx.DARK)
                    gfx.rect(margin, sy + 2, dw, dh)

            elif itype == "image_missing":
                margin, usable_w, placeholder = item[3], item[4], item[5]
                gfx.color(gfx.DARK)
                gfx.rect(margin, sy + 1, usable_w, ih - 2)
                gfx.font(f_mono)
                gfx.text(margin + 4, sy + ih - 5, placeholder)

        # Scrollbar indicator
        if self.content_height > vh:
            bar_h = max(10, (vh * vh) // self.content_height)
            max_scroll = max(1, self.content_height - vh)
            bar_y = top_h + ((vh - bar_h) * self.scroll_y) // max_scroll
            gfx.color(gfx.DARK)
            gfx.fill_rect(w - 3, bar_y, 3, bar_h)

        # Top Status Bar
        gfx.color(gfx.BLACK)
        gfx.fill_rect(0, 0, w, top_h)
        gfx.color(gfx.WHITE)
        gfx.font(gfx.FONT_SMALL)

        if self.search_mode:
            status = "/" + self.search_query + "_"
        elif self.search_query:
            m_info = "{}/{}".format(self.match_idx + 1, len(self.matches)) if self.matches else "0/0"
            status = "Find:{} [{}]".format(self.search_query, m_info)
        else:
            fname = path_basename(self.current_file)
            pct = 100
            if self.content_height > vh:
                pct = min(100, (self.scroll_y * 100) // max(1, self.content_height - vh))
            link_tag = ""
            if self.selected_link >= 0 and self.selected_link < len(self.links):
                link_tag = " >" + self.links[self.selected_link][0]
            status = "{} [{}] {}%{}".format(fname, p_name[0], pct, link_tag)

        max_status_chars = max(8, (w - 8) // 6)
        if len(status) > max_status_chars:
            status = status[:max_status_chars]
        gfx.text(4, top_h - 5, status)

        gfx.present()

    def handle_key(self, key):
        if key is None:
            return True

        vh = self.view_height()
        max_scroll = max(0, self.content_height - vh)
        step = FONT_PRESETS[self.preset_idx][8] * 2

        # Search input mode
        if self.search_mode:
            if key in (gfx.KEY_ESCAPE, 27):
                self.search_mode = False
                return True
            if key in (10, 13):
                self.search_mode = False
                self.run_search(jump=True)
                return True
            if key in (gfx.KEY_DELETE, 8, 127):
                if self.search_query:
                    self.search_query = self.search_query[:-1]
                return True
            if isinstance(key, int) and 32 <= key <= 126:
                self.search_query += chr(key)
                return True
            return True

        # Normal navigation mode
        if key in (gfx.KEY_ESCAPE, 27):
            if self.search_query:
                self.search_query = ""
                self.matches = []
                self.match_idx = -1
                return True
            if self.selected_link != -1:
                self.selected_link = -1
                return True
            return False

        if key == ord("q"):
            return False

        # Start search
        if key == ord("/"):
            self.search_mode = True
            self.search_query = ""
            return True

        # Next / Previous search match
        if key == ord("n") and self.matches:
            self.match_idx = (self.match_idx + 1) % len(self.matches)
            self.jump_to_match()
            return True
        if key == ord("N") and self.matches:
            self.match_idx = (self.match_idx - 1) % len(self.matches)
            self.jump_to_match()
            return True

        # Scroll down / up
        if key in (gfx.KEY_DOWN, ord("j")):
            self.scroll_y = min(max_scroll, self.scroll_y + step)
            return True
        if key in (gfx.KEY_UP, ord("k")):
            self.scroll_y = max(0, self.scroll_y - step)
            return True
        if key in (gfx.KEY_PAGE_DOWN, ord(" ")):
            self.scroll_y = min(max_scroll, self.scroll_y + vh - 16)
            return True
        if key == gfx.KEY_PAGE_UP:
            self.scroll_y = max(0, self.scroll_y - (vh - 16))
            return True
        if key == ord("g"):
            self.scroll_y = 0
            return True
        if key == ord("G"):
            self.scroll_y = max_scroll
            return True

        # Link selection
        if key in (9, gfx.KEY_RIGHT):
            if self.links:
                self.selected_link = (self.selected_link + 1) % len(self.links)
                self.ensure_link_visible()
            return True
        if key == gfx.KEY_LEFT:
            if self.links:
                self.selected_link = (self.selected_link - 1) % len(self.links)
                self.ensure_link_visible()
            return True

        # Open selected link
        if key in (10, 13):
            if 0 <= self.selected_link < len(self.links):
                _, target_path = self.links[self.selected_link]
                if target_path:
                    self.load_file(target_path, push_history=True)
            return True

        # Navigate back in history
        if key in ( ord("b"), ord("b")):
            self.go_back()
            return True

        # Font size cycling
        if key in (ord("+"), ord("=")):
            if self.preset_idx < len(FONT_PRESETS) - 1:
                self.preset_idx += 1
                self.rebuild_layout()
                if self.search_query:
                    self.run_search(jump=False)
            return True
        if key in (ord("-"), ord("_")):
            if self.preset_idx > 0:
                self.preset_idx -= 1
                self.rebuild_layout()
                if self.search_query:
                    self.run_search(jump=False)
            return True

        return True


def main():
    if len(sys.argv) < 2:
        print("Usage: mdview.py <markdown_file>")
        return

    target_file = sys.argv[1]
    viewer = MarkdownViewer(target_file)

    gfx.begin()
    try:
        viewer.rebuild_layout()
        viewer.render()
        while not solaros.should_exit():
            key = gfx.getch(200)
            if key is not None:
                if not viewer.handle_key(key):
                    break
                viewer.render()
    finally:
        viewer.close_images()
        gfx.end()


if __name__ == "__main__":
    main()
