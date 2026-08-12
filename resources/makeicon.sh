#!/bin/zsh
# Builds MyIcon.icns from icon.png (same approach as AtomDataExtractor's
# resources/makeicon.sh). Run from this directory once icon.png exists;
# dm41.spec picks up ../resources/MyIcon.icns automatically once it's
# there -- no icon.png yet, so today's build just runs without a custom
# icon (see dm41.spec's `icon = ICON_PATH if os.path.exists(...) else None`).
#
# icon.png should be a large (e.g. 1024x1024) square PNG.

mkdir -p MyIcon.iconset
for i in 64 128 256 512; do
    sips -z $i $i icon.png --out MyIcon.iconset/icon_${i}x${i}.png
done
iconutil -c icns MyIcon.iconset

rm -rf MyIcon.iconset
