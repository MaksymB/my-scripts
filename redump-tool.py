#!/usr/bin/python3

import argparse
import hashlib
import os
import shutil
import xml.etree.ElementTree as ET
import zipfile
import difflib

def main():
    parser = argparse.ArgumentParser(description="Command line tool to maintain Redump image set.")

    parser.add_argument('--import-from', type=str, help="Import known images from the given directory.")
    parser.add_argument('--test-import', type=str, help="Perform full test of the images in the given directory.")
    parser.add_argument('--dry', action='store_true', help="Perform dry run (no actual changes).")
    parser.add_argument('--test', action='store_true', help="Test the library (no check sums).")
    parser.add_argument('--test-full', action='store_true', help="Test the library (with check sums).")

    args = parser.parse_args()

    archive_path = find_db_export_archive('.db')
    xml_content = extract_dat_from_archive(archive_path)
    root = ET.fromstring(xml_content)

    print_header(root)

    games_data = load_games_data_from_db(root, args)

    print(f"{len(games_data)} disk images in the databases")

    if args.test:
        test_library(games_data, False, ".")

    if args.test_full:
        test_library(games_data, True, ".")

    if args.test_import:
        test_library(games_data, True, args.test_import)

    if args.import_from:
        games_data_to_import = load_games_data_to_import(args.import_from)
        print(f"{len(games_data_to_import)} games to import")

        import_games(games_data_to_import, games_data, args.dry)

def test_library(games_data, test_hashes, path):
    tested_games = 0
    passed_tests = 0
    failed_tests = 0
    warnings = 0

    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        dir_name = os.path.basename(os.path.abspath(root))

        file_names = []
        hashes = []
        for file_name in files:
            _, file_ext = os.path.splitext(file_name)
            if (file_ext == '.bin' or file_ext == '.cue') and not file_name.startswith('.'):
                file_names.append(file_name)
                if test_hashes:
                    file_path = os.path.abspath(os.path.join(root, file_name))
                    file_sha1 = compute_sha1_of_file(file_path)
                    hashes.append(file_sha1)
            else:
                print(f"WARNING: garbage file ignored: '{os.path.join(root, file_name)}'")
                warnings = warnings + 1

        if len(file_names) > 0:
            game_name = dir_name
            ok = True
            if game_name in games_data:
                expected_file_names = [f.name for f in games_data[game_name].files]
                expected_file_names.sort()
                file_names.sort()

                if test_hashes:
                    expected_hashes = [f.sha1 for f in games_data[game_name].files]
                    expected_hashes.sort()
                    hashes.sort()
                    ok = ok and hashes == expected_hashes

                ok = ok and file_names == expected_file_names

            else:
                print(f"Unknown game: '{game_name}'")
                ok = False

            print(f'[{"OK" if ok else "FAILED"}] {dir_name}')

            tested_games = tested_games + 1
            if ok:
                passed_tests = passed_tests + 1
            else:
                failed_tests = failed_tests + 1

    print(f"Games tested: {tested_games}")
    print(f"  - Passed tests: {passed_tests}")
    print(f"  - Failed tests: {failed_tests}")
    print(f"  - warnings: {warnings}")

def import_games(games_data_to_import, games_data, dry):
    for name in games_data_to_import:
        if name in games_data:
            gd_import = games_data_to_import[name]
            gd_db = games_data[name]

            target_game_dir = os.path.abspath(gd_db.name)
            if os.path.isdir(target_game_dir):
                print(f"WARNING: game already exists in the library: {name}")
                continue

            hashes_import = [f.sha1 for f in gd_import.files]
            hashes_db = [f.sha1 for f in gd_db.files]
            if set(hashes_import) == set(hashes_db):
                print(f"Importing {name}...")
                if not dry:
                    os.makedirs(target_game_dir, exist_ok=False)
                for f in gd_db.files:
                    from_path = get_import_file_path(gd_import, f.sha1)
                    to_path = os.path.join(target_game_dir, f.name)
                    print(f"- {from_path}")
                    print(f"  -> {to_path}")
                    if not dry:
                        shutil.move(from_path, to_path)
            else:
                print(f"WARNING: validation failed: '{name}'")
        else:
            print(f"WARNING: game not found in the DB: '{name}'")
            close_matches = difflib.get_close_matches(name, games_data.keys())
            if len(close_matches) > 0:
                for possible_name in close_matches:
                    print(f"  - it could be '{possible_name}'. Trying...")

                    renaming_succeeded = try_to_rename_the_game_during_import(games_data[possible_name], games_data_to_import[name], dry)

                    if renaming_succeeded:
                        print("Done!")
                        break
                
def try_to_rename_the_game_during_import(gd_db, gd_import, dry):
    target_bins_hashes = {}
    target_cue_sha1 = None
    target_cue_fpath = None
    bins_to_import_hashes = dict([(f.sha1, os.path.join(gd_import.description, f.name))
                                  for f in gd_import.files
                                  if os.path.splitext(f.name)[1] == '.bin'])
    bin_files_renamings = {}
    target_game_dir = os.path.abspath(gd_db.name)

    for f in gd_db.files:
        to_path = os.path.join(target_game_dir, f.name)
        _, ext = os.path.splitext(f.name)
        if ext == '.cue':
            if target_cue_sha1 != None:
                print(f"ERROR: '.cue' file is not unique for game '{gd_db.name}'")
                return False
            target_cue_sha1 = f.sha1
            target_cue_fpath = to_path
        else:
            target_bins_hashes[f.sha1] = to_path
            from_path = get_import_file_path(gd_import, f.sha1)
            if from_path == None:
                print(f"NOT FOUND: {f.sha1}")
                print(f"INFO: there is no one-to-one match in bin files.")
                return False

            bin_files_renamings[os.path.basename(from_path)] = f.name

        if target_cue_sha1 == None:
            print(f"ERROR: '.cue' file not found for game '{gd_db.name}'")
            return False

    orig_cue_fpath = get_cue_file_path(gd_import)
    if orig_cue_fpath == None:
        print(f"ERROR: '.cue' file not found for the game being imported - '{gd_import.name}'")
        return False

    with open(orig_cue_fpath, 'rb') as file:
        cue_content = file.read()
    modified_cue_content = replace_substrings(cue_content, bin_files_renamings)
    modified_cue_sha1 = calculate_sha1(modified_cue_content)

    if modified_cue_sha1 != target_cue_sha1:
        print("Failed to modify '.cue' file")
        print(f"  - Expected SHA1: {target_cue_sha1}")
        print(f"  - Actual SHA1:   {modified_cue_sha1}")
        return False

    if set(target_bins_hashes) == set(bins_to_import_hashes):
        print(f"Importing '{gd_import.name}' as '{gd_db.name}'...")
        if not dry:
            os.makedirs(target_game_dir, exist_ok=False)

        print(f"- [tweaked] {orig_cue_fpath}")
        print(f"  -> {target_cue_fpath}")

        if not dry:
            with open(target_cue_fpath, 'wb') as file:
                file.write(modified_cue_content)

        for sha1 in bins_to_import_hashes:
            from_path = bins_to_import_hashes[sha1]
            to_path = target_bins_hashes[sha1]
            print(f"- {from_path}")
            print(f"  -> {to_path}")
            if not dry:
                shutil.move(from_path, to_path)
    else:
        print("Binaries mismatch")
        return False

    return True

def calculate_sha1(data):
    sha1 = hashlib.sha1()
    sha1.update(data)
    return sha1.hexdigest()

def replace_substrings(content, replacements):
    for old, new in replacements.items():
        content = content.replace(old.encode('utf-8'), new.encode('utf-8'))
    return content

def get_cue_file_path(gd_import):
    for f in gd_import.files:
        _, ext = os.path.splitext(f.name)
        if ext == '.cue':
            return os.path.join(gd_import.description, f.name)
    return None

def get_import_file_path(gd_import, sha1):
    for f in gd_import.files:
        if sha1 == f.sha1:
            return os.path.join(gd_import.description, f.name)
    return None

def find_db_export_archive(directory):
    db_archives = list(filter(lambda p : p.endswith(".zip"), os.listdir(directory)))

    if len(db_archives) == 0:
        raise FileNotFoundError("DB arhive not found.")

    if len(db_archives) > 1:
        db_archives.sort(reverse = True)
        print(f"WARNING: More than one DB archive found:")
        for db_archive in db_archives:
            print(f"  - {db_archive}")
        print(f"The most recent will be used: {db_archives[0]}\n")

    return os.path.join(directory, db_archives[0])

def extract_dat_from_archive(archive_path):
    with zipfile.ZipFile(archive_path, 'r') as zip_ref:
        xml_files = [name for name in zip_ref.namelist() if name.endswith('.dat')]
        if len(xml_files) != 1:
            raise FileNotFoundError("The archive does not contain exactly one XML file.")
        with zip_ref.open(xml_files[0]) as xml_file:
            return xml_file.read()

def print_header(root):
    header = root.find('header')
    
    if header is not None:
        name = header.find('name')
        description = header.find('description')

        if name is not None and description is not None:
            print(f"Redump database {name.text}")
            print(description.text)
        else:
            for child in header:
                print(f"{child.tag}: {child.text}")
    else:
        print("Warning: header not found")

class FileInfo:
    def __init__(self, name, sha1):
        self.name = name
        self.sha1 = sha1

class GameInfo:
    def __init__(self, name, category, description, files):
        self.name = name
        self.category = category
        self.description = description
        self.files = files

def load_games_data_from_db(root, args):
    games_data = {}
    for game in root.findall('game'):
        game_name = game.attrib.get('name')

        category = game.find('category').text
        description = game.find('description').text

        fs = []
        for rom_file in game.findall('rom'):
            rom_file_name = rom_file.get('name')
            rom_file_sha1 = rom_file.get('sha1')

            f = FileInfo(rom_file_name, rom_file_sha1)
            fs.append(f)

        g = GameInfo(game_name, category, description, fs)
        games_data[game_name] = g

    return games_data

def compute_sha1_of_file(file_path):
    sha1 = hashlib.sha1()
    with open(file_path, 'rb') as f:
        while chunk := f.read(8192):
            sha1.update(chunk)
    return sha1.hexdigest()

def load_games_data_to_import(import_path):
    games_data = {}

    for root, dirs, files in os.walk(import_path):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        dir_name = os.path.basename(os.path.abspath(root))

        fs = []
        for file_name in files:
            _, file_ext = os.path.splitext(file_name)
            if (file_ext == '.bin' or file_ext == '.cue') and not file_name.startswith('.'):
                file_path = os.path.abspath(os.path.join(root, file_name))
                file_sha1 = compute_sha1_of_file(file_path)
                f = FileInfo(file_name, file_sha1)
                fs.append(f)
            else:
                print(f"WARNING: ignored unknown file type: {file_name}")

        if len(fs) > 0:
            game_name = dir_name
            games_data[dir_name] = GameInfo(dir_name, 'IMPORT', os.path.abspath(root), fs)

    return games_data

if __name__ == "__main__":
    main()

