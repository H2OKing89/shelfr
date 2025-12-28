# MyAnonamouse (MAM) Supported BBCode Reference

This document lists all BBCode tags supported by MyAnonamouse for use in descriptions, comments, and the Shoutbox.

**Source:** MyAnonamouse forum post from 2019-10-05 (Shoutbox BBCode Guide)

---

## Basic Formatting Tags

| Tag | Usage | Result |
| --- | --- | --- |
| `[i]text[/i]` | Italics | *text* |
| `[b]text[/b]` | Bold | **text** |
| `[u]text[/u]` | Underline | Underlined text |
| `[s]text[/s]` | Strikethrough | ~~text~~ |

---

## Font and Size Tags

### Font Size

```bbcode
[size=1]smallest[/size]
[size=2]small[/size]
[size=3]normal[/size]
[size=4]large[/size]
[size=5]larger[/size]
[size=6]largest[/size]
```

Supports sizes **1 through 6**. Size 3 is typically the default.

### Font Face

```code
[font=Courier New]Text in Courier New font[/font]
[font=Arial]Text in Arial font[/font]
[font=Verdana]Text in Verdana font[/font]
```

Common fonts: Comic Sans MS, Lucida Console, Papyrus, Verdana, Vivaldi, Curlz MT, Courier New

**Note:** Font will display as default if not installed on user's system.

### Font Color

```bbcode
[color=red]Red text[/color]
[color=#FF0000]Red text using hex code[/color]
[color=#3aa6ff]Blue text using hex code[/color]
```

Supports:

- Color names (red, blue, green, etc.)
- HEX color codes (#RRGGBB format)

**Tip:** Use a [text colorizer](https://www.colourlovers.com/palette/colors) to generate color codes and test gradations.

### Superscript and Subscript

```bbcode
[sup]superscript text[/sup]    ← Text appears above the line
[sub]subscript text[/sub]      ← Text appears below the line
```

Example: H[sub]2[/sub]O, E=mc[sup]2[/sup]

---

## Layout Tags

### Center Alignment

```bbcode
[center]Centered text[/center]
```

---

## Links and Media

### URL Links

Method 1 - Display full URL:

```bbcode
[url]https://www.myanonamouse.net[/url]
```

Shows as: <https://www.myanonamouse.net>

Method 2 - Display custom text:

```bbcode
[url=https://www.myanonamouse.net]Click here to visit MAM[/url]
```

Shows as: Click here to visit MAM

### Images

```bbcode
[img]http://example.com/image.gif[/img]
```

Image that links to full size:

```bbcode
[imgUrl]http://example.com/thumb.gif[/imgUrl]
```

---

## Special Features

### Alt Codes (Unicode Symbols)

You can insert unicode symbols not found on a regular keyboard using Alt Codes:

Examples:

- Musical notes: ♫ ♪
- Mathematical symbols: ≠ ∞ ± √
- Greek letters: α β γ δ
- Arrows: → ← ↑ ↓

**Resource:** [Alt Code Unicode Symbol Reference](https://www.alt-codes.net/)

### Actions

Prefix text with `/me` for action-style messages:

```bbcode
/me does something cool
```

Shows as: *does something cool* (in action formatting)

---

## Common Usage Examples

### MAM Description Template

```bbcode
[center][size=6][b][color=#3aa6ff]Book Title[/color][/b][/size][/center][br][br]
[b][color=#3aa6ff]Synopsis[/color][/b][br]
Your synopsis text here with [b]bold[/b] and [i]italic[/i] formatting as needed.[br][br]
[b][color=#3aa6ff]Book Info[/color][/b][br]
• [b]Author:[/b] Author Name[br]
• [b]Narrator:[/b] Narrator Name[br]
• [b]Publisher:[/b] Publisher Name[br]
• [b]Genre:[/b] Genre Tags[br]
• [b]Audible:[/b] [url=https://www.audible.com/pd/ASIN]Audible Link[/url][br][br]
[b][color=#3aa6ff]Audio Info[/color][/b][br]
• [b]Format:[/b] M4B[br]
• [b]Duration:[/b] 10 hours[br]
• [b]Chapters:[/b] Yes
```

**Note:** When using MAM's JSON import feature, use `[br]` tags for line breaks.
The JSON file should contain both `[br]` tags and `\n` newlines for proper rendering.

### Emphasized Text

```bbcode
[b]Important announcement![/b] - This is really [u]important[/u].
The book has [s]100[/s] 50 ratings.
```

---

## Line Breaks

### Using [br] Tags

```bbcode
[br]
```

Use `[br]` for explicit line breaks in MAM descriptions. This is especially important when:

- Using MAM's JSON fast-fill import feature
- Building structured descriptions with sections
- Creating chapter listings

**Note:** When submitting via JSON import, include both `[br]` tags and `\n` newlines in the JSON string.

---

## Not Supported

The following tags are **NOT** supported by MAM:

- `[h1]`, `[h2]`, etc. - Heading tags
- `[code]` - Code formatting
- `[quote]` - Quote formatting
- `[list]` - Unordered lists
- `[ol]` - Ordered lists
- `[table]` - Tables
- `[spoiler]` - Spoiler tags

---

## Notes

1. **Always close tags** - Every opening tag must have a corresponding closing tag with a forward slash
2. **Nesting** - Most tags can be nested for combined formatting: `[b][i]Bold and italic[/i][/b]`
3. **Case insensitive** - Tags work in any case: `[B]`, `[b]`, `[B]` are equivalent
4. **Whitespace** - Leading/trailing whitespace in tags is ignored
5. **Line breaks** - Use actual newline characters (Enter key), NOT `[br]` tags
6. **HTML entities** - Do NOT use HTML entities like `&nbsp;` - plain text only

---

## Related Documentation

- [MAM API Documentation](./AUDIOBOOKSHELF_API.md)
- [HTML to BBCode Conversion](../../src/mamfast/metadata.py#_html_to_bbcode)
