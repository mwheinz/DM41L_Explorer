The HP41/DM41 character set is a subset of HP's FOCAL character set. FOCAL is
similar to ASCII but not the same. In particular it includes symbols that are
not in ASCII. To support these, we use 3-character sequences called
"trigraphs".

The simplest form of a trigraph is a backslash followed by three decimal digits. This
specifies a literal hex representation as a character. (For example, "\\65"
should encode as the a literal 0x41 character, which is the letter "A".

In addition to this, some characters can be represented by two or three
characters meant to resemble the symbol in question. This are listed in the
following table:


| CHARACTER CODE | Substitution | Description |
|--|--|--|
| 0x00 | \\-- | A high horizontal bar. |
| 0x01 | \\x | times symbol | 
| 0x0C | \\u | micro sumbol |
| 0x0D | \\<) | angle symbol |
| 0x1D | \\/= | not equal |
| 0x5C | \\\\ | backslash | 
| 0x5E | \^\| | up arrow |
| 0x60 | \\T | tee |
| 0x7E | \\E | Sigma | 
| 0x7F | \\+ | Append |

