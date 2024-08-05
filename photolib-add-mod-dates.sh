#!/bin/bash

shopt -s nocaseglob

for filename in *.jpg; do
    echo "$filename $(stat -f '%Sm' -t '%Y-%m-%d %H-%M-%S' "$filename")"
    exiftool -Alldates="$(stat -f '%Sm' -t '%Y-%m-%d %H-%M-%S' "$filename")" "$filename"
done

for filename in *.jpeg; do
    echo "$filename $(stat -f '%Sm' -t '%Y-%m-%d %H-%M-%S' "$filename")"
    exiftool -Alldates="$(stat -f '%Sm' -t '%Y-%m-%d %H-%M-%S' "$filename")" "$filename"
done

shopt -u nocaseglob
