#!/usr/bin/env python3
import os
import sys
from transliterate import translit

# Check if the directory argument is provided
if len(sys.argv) != 2:
    print("Usage: ./transliterate_names.py /path/to/directory")
    sys.exit(1)

# Get the directory path from command-line argument
directory = sys.argv[1]

# Check if the directory exists
if os.path.isdir(directory):
    # Iterate through each file in the directory
    for filename in os.listdir(directory):
        filepath = os.path.join(directory, filename)
        if os.path.isfile(filepath):
            # Transliterate the filename from Cyrillic to Latin
            new_filename = translit(filename, 'ru', reversed=True)
            # Rename the file with the transliterated filename
            os.rename(filepath, os.path.join(directory, new_filename))
            print(f"Transliterated {filename} to {new_filename}")
    print("Transliteration complete.")
else:
    print(f"Directory not found: {directory}")

