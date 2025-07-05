#!/usr/bin/env python3

import inspect
import json
import os
import re
import sys
import tempfile

from collections import defaultdict
from immichapi import ImmichApi
from subprocess import Popen, PIPE


class ImmichCli(object):
    """
    def get(self, path, body=None, req_headers=None, method="get"):
    def getAssetDuplicates(self):
    def getUniqueOriginalPaths(self):
    def getAssetsByOriginalPath(self, path):
    def getAssetInfo(self, assetid):
    """

    def __init__(self, *args, url="http://localhost:2283/api", dryrun=False, verbose=False):
        self.url = url
        self.dryrun = dryrun
        self.verbose = verbose
        #self.api = ImmichApi(url=self.url, dry_run=self.dryrun, dupsfile="dup.json")
        self.api = ImmichApi(url=self.url, dupsfile="dup.json")
        self.folder_cache = []
        self.upload_device_id = "63ae08d41c982c437c6967d4b885fad35668ad555e810dad676807339af70a7a"
        self.verbs = {
            "get": self.get,
            "list": self.list,
            "db": self.do_db,
            "dedup": self.dedup,
        }
        self.modifiers = set()

    def __call__(self, command: list):
        if not command:
            raise Exception("No command")

        self.modifiers.clear()

        possible_modifiers = []

        verb = command[0]
        command = command[1:]

        while command and command[0] in possible_modifiers:
            self.modifiers.add(command[0])
            command = command[1:]

        if verb in self.verbs:
            return json.dumps(self.verbs[verb](command))

        raise Exception(f"Unknown command: {verb}")

    @property
    def one(self):
        return "one" in self.modifiers

    def get(self, command):
        if not command:
            raise Exception("Nothing to get")

        possible_modifiers = ["one"]
        while command[0] in possible_modifiers:
            self.modifiers.add(command[0])
            command = command[1:]

        predicate = command[0]

        if predicate not in ["asset", "library", "album"]:
            raise Exception(f"Cannot get object of type {predicate}")

        if predicate == "asset":
            return self.get_asset(command[1:])

        if predicate == "library":
            return self.get_library(command[1:])

        if predicate == "album":
            return self.get_album(command[1:])

    def get_asset(self, command):
        if not command:
            raise Exception("No asset to get")

        results = []
        for assetId in command:
            try:
                results.append(self.api.getAssetInfo(assetId))
            except Exception as e:
                results.append({"error": f"failed to fetch assetId {assetId}", "exception": str(e)})
        if self.one:
            for res in results:
                if "error" not in res:
                    return res
            return results[0]
        return results

    def get_library(self, command):
        if not command:
            raise Exception("No library to get")

        results = []
        for libraryId in command:
            try:
                results.append(self.api.getLibrary(libraryId))
            except Exception as e:
                results.append({"error": f"failed to fetch libraryId {libraryId}", "exception": str(e)})
        if self.one:
            for res in results:
                if "error" not in res:
                    return res
            return results[0]
        return results

    def get_album(self, command):
        album_keys = ["assets", "id", "albumName"]
        keys_to_extract = []
        while command[0] in album_keys:
            keys_to_extract.append(command[0])
            command = command[1:]
        results = {}
        for album in self.api.getAlbums():
            if album["albumName"] not in command:
                continue
            full_album = self.api.getAlbumInfo(album["id"])
            if keys_to_extract:
                results[album["albumName"]] = dict((k, full_album[k]) for k in keys_to_extract)
            else:
                results[album["albumName"]] = full_album
        if results and self.one:
            return list(results.values())[0]
        return results

    def list(self, command):
        if not command:
            raise Exception("Nothing to list")

        predicate = command[0]

        if predicate not in ["library", "single_stored_assets", "album"]:
            raise Exception(f"Cannot list object of type {predicate}")

        if predicate == "library":
            return self.list_library(command[1:])

        if predicate == "single_stored_assets":
            return self.list_single_stored_assets(command[1:])

        if predicate == "album":
            return(self.list_album(command[1:]))

    def list_library(self, command):
        if self.one:
            return self.api.getAllLibraries()[0]
        return self.api.getAllLibraries()

    def list_single_stored_assets(self, command):
        result = self.find_all_single_stored_assets()
        return result

    def list_album(self, command):
        keys_to_extract = []
        album_keys = ["assets", "id"]
        while command[0] in album_keys:
            keys_to_extract.append(command[0])
            command = command[1:]
        results = {}
        all_albums = dict(((album["albumName"], album) for album in self.api.getAlbums()))
        for album_name in command:
            album = all_albums.get(album_name, None)
            if not album:
                continue
            if keys_to_extract:
                results[album_name] = dict(((k, album.get(k, "")) for k in keys_to_extract))
            else:
                results[album_name] = album
        if self.one:
            return list(results.values())[0]
        return results

    def do_db(self, command):
        return self.db(" ".join(command))

    @property
    def folders(self):
        """
        Every path to asset originals.
        """
        if not self.folder_cache:
            self.folder_cache = self.api.getUniqueOriginalPaths()
        return self.folder_cache

    def verb(self, msg):
        if self.verbose:
            print(msg, file=sys.stderr)

        
    def dups(self, asset=None):
        return self.api.dups(asset=asset)

    def find_true_path(self, path):
        if not path.startswith("/"):
            path = "/" + path
        if path.startswith("/dropbox"):
            return "/mnt" + path
        if path.startswith("/photos"):
            return "/mnt/files" + path
        if path.startswith("upload"):
            return path.replace("upload/upload", "/mnt/files/immich/upload")
        raise(Exception("Unable to find true path for {path}"))

    def subdirs(self, path: str):
        """
        All of the asset originals folders that are direct children of the tail of path.
        Not the whole tree, just what's in the first level under path.
        This is a useful step in finding the "album" folders in a Google Takeout folder.
        """
        path = self.api.fix_path(path) # normalize path to look like "photos/"
        subs = set()
        for folder in self.folders:
            if folder.startswith(path):
                subs.add(folder[len(path):].split("/")[0])
        return subs

    def assets_under_path(self, path: str):
        """
        Every asset underneath a single path. Not just the immediate subdirectories,
        but the whole tree.

        Loops over every folder that contains an asset, matches the beginning of that
        folder against the provided path, and conditionaly adds that folder's assets
        to the return list.
        """
        assets = []
        for folder in self.folders:
            if folder.startswith(path):
                assets.extend(self.api.getAssetsByOriginalPath(folder))
        return assets

    def assets_by_subdir(self, path: str):
        return dict((sub, self.assets_under_path(os.path.join(path, sub))) for sub in self.subdirs(path))

    def album_assets(self, albumId: str):
        return self.api.getAlbumInfo(albumId)["assets"]

    def google_folder_assets(self):
        goog_year_folders = {}
        goog_album_folders = {}
        for folder in self.folders:
            if re.match("^/?photos/GooglePhotos/Photos from [0-9]{4}$", folder):
                goog_year_folders[folder] = [asset["id"] for asset in self.assets_under_path(folder)]
            elif re.match("^/?photos/GooglePhotos/.+$", folder):
                goog_album_folders[folder] = self.assets_under_path(folder)
        return goog_year_folders, goog_album_folders

    def redundant_google_folders(self):
        goog_year_folders, goog_album_folders = self.google_folder_assets()
        redundant_albums = []
        for album, album_assets in goog_album_folders.items():
            if self.verbose: print(f"Processing album {album} with {len(album_assets)} photos.")
            #if self.verbose: print(f"Processing album {album} with {len(album_assets)} photos. One is {album_assets[0]}.")
            redundant = True
            for album_asset in album_assets:
                album_asset_dup_id = album_asset.get("duplicateId", None)
                year_folder = None
                if album_asset_dup_id:
                    for dup_set in self.dups():
                        if dup_set["duplicateId"] == album_asset_dup_id:
                            #print(f"dup set for album photo {album_asset['id']}: {dup_set}")
                            for asset in dup_set["assets"]:
                                _match = re.search("^/?photos/GooglePhotos/(Photos from [0-9]{4})/.*", asset["originalPath"])
                                if _match:
                                    year_folder = _match.group(1)
                                    #print(f"Photo {album_asset['originalPath']} is in year folder {year_folder}")
                                    break
                if not year_folder:
                    redundant = False
                    self.verb(f"Photo {album_asset['originalPath']} is not in any GooglePhotos year folder.")
            if album_assets and redundant:
                redundant_albums.append(album)

        return redundant_albums

    def google_folder_to_album(self, folder: str, library: dict = None):
        """
        Expects the path to a folder under an import path which contains as part
        of it (or the whole of it) a Google Takeout import.
        
        For every asset in the folder, make sure it has a dup in a year folder.
        Put that dup in a list so that we can later add them all to a new album.
        NB: we're not making the album if any of the folder assets don't have an
        appropriate dup, we're raising an exception instead.
        Once we have all the dups, find or create the new album and put them in there.
        Finally, add the folder to the library's exclude path. If the first element in
        the folder's path uniquely identifies the library, this should find it. Otherwise,
        you can pass the library in a as a parameter.
        """

        self.verb(f"Processing folder {folder}")

        albums = self.api.getAlbums()
        folder_album = folder.split("/")[-1]
        albumId = None
        for album in albums:
            if album["albumName"] == folder_album:
                self.verb(f"Found album {album['albumName']} with id {album['id']}, skipping")
                return album["id"]

        assets_for_album = []
        for toxic_asset in self.assets_under_path(folder):
            dups = self.dups(toxic_asset)
            if not dups:
                raise Exception(f"asset {toxic_asset['id']} in folder {folder} has no duplicates")
            clean_asset = None
            for dup in dups:
                if "GooglePhotos/Photos from " in dup["originalPath"]:
                    clean_asset = dup
                    break
            if clean_asset == None:
                raise Exception(f"asset {toxic_asset['id']} in folder {folder} has no duplicate in a Google Photos \"year\" folder")

            assets_for_album.append(clean_asset["id"])

            for album in self.api.getAlbums(toxic_asset["id"]):
                self.verb(f"Replacing toxic asset with clean asset in album {album['albumName']}")
                if self.dryrun:
                    self.verb(f"self.api.removeAssetFromAlbum({album['id']}, {toxic_asset['id']})")
                    self.verb(f"self.api.addAssetsToAlbum({album['id']}, {[clean_asset['id']]})")
                else:
                    self.api.removeAssetFromAlbum(album["id"], toxic_asset["id"])
                    self.api.addAssetsToAlbum(album["id"], [clean_asset["id"]])

        if self.dryrun:
            self.verb(f"album = self.api.createAlbum({folder_album})")
        else:
            album = self.api.createAlbum(folder_album)
        albumId = album["id"]
        self.verb(f"No album with name {folder_album}, created {albumId}")

        self.verb(f"folder {folder} found {len(assets_for_album)} clean assets for album {folder_album}")

        if self.dryrun:
            self.verb(f"self.api.addAssetsToAlbum({albumId}, {assets_for_album})")
        else:
            self.api.addAssetsToAlbum(albumId, assets_for_album)

        if library is None:
            slashfolder = "/" + folder
            for lib, path in ((lib, path) for lib in self.api.getAllLibraries() for path in lib["importPaths"]):
                if slashfolder.startswith(path):
                    library = lib
                    break
        if library is None:
            raise Exception(f"Unable to find library for folder {folder}")

        if all (folder not in pattern for pattern in library["exclusionPatterns"]):
            patterns = library["exclusionPatterns"] + [f"/{folder}/**"]
            if self.dryrun:
                self.verb(f"self.api.updateLibrary({library['id']}, exclusionPatterns = {patterns})")
            else:
                self.api.updateLibrary(library["id"], exclusionPatterns = patterns)
        self.verb(f"Added exclusion pattern \"{folder}\" to library {library['name']}")

        return albumId

    def find_album(self, album_name: str):
        for album in self.api.getAlbums():
            if album["albumName"] == album_name:
                return album
        return None

    def find_album_id(self, album_name: str):
        album = self.find_album(album_name)
        if album and "id" in album:
            return album["id"]
        return None

    def find_person(self, name: str):
        person_objects = self.api.searchPerson(name)
        if type(person_objects) != list:
            return None
        if len(person_objects) == 0:
            return None
        if "id" not in person_objects[0]:
            return None
        return person_objects[0]

    def find_person_id(self, name: str):
        person = self.find_person(name)
        if not person or "id" not in person:
            return ""
        return person["id"]

    def exclude_album_assets(self, album_name):
        # exclude all assets in album
        # this is a bad idea, immich will only accept a total of 128
        # exclusion patterns for a library. instead, rework this to
        # set isArchived to "true" on these assets, hiding them in
        # the library.
        
        ## get all the assets in the album
        album_id = self.find_album_id(album_name)
        if album_id is None:
            raise Exception("No album named {album_name}")
        assets = self.api.getAlbumInfo(album_id)["assets"]

        ## find each of their libraries
        ## build the list of patterns for each library
        library_patterns = defaultdict(list)
        for asset in assets:
            library_patterns[asset["libraryId"]].append(asset["originalPath"])

        ex_asset_count = 0
        updated_library_count = 0
        ## update each library with the patterns
        for library in self.api.getAllLibraries():
            if library["id"] in library_patterns:
                updated_library_count += 1
                ex_patterns = library["exclusionPatterns"]
                for pattern in library_patterns[library["id"]]:
                    if pattern not in ex_patterns:
                        ex_patterns.append(pattern)
                        ex_asset_count += 1
                print(self.api.updateLibrary(library["id"], exclusionPatterns = ex_patterns))

        return {"updated library count": updated_library_count, "added asset count": ex_asset_count}

    def delete_and_remove_originals(self, assets):
        for asset in assets:
            path = self.find_true_path(asset["originalPath"])
            print(f"Deleting asset {asset['id']} at path {path}")
            self.api.deleteAssets([asset["id"]])
            proc = Popen(["rm", path], stdout=PIPE, stderr=PIPE)
            stdout, stderr = proc.communicate()
            if proc.returncode != 0:
                print(f"Error {proc.returncode} removing {path}: {stderr}")

    def delete_and_remove_album_assets(self, album_name):
        album_id = self.find_album_id(album_name)
        if album_id is None:
            raise Exception("No album named {album_name}")
        assets = self.api.getAlbumInfo(album_id)["assets"]
        self.delete_and_remove_originals(assets)

    def get_all_libraries(self):
        libraries = dict((library["id"], library) for library in self.api.getAllLibraries())
        libraries[self.upload_device_id] = {"id": self.upload_device_id, "name": "upload"}
        return libraries

    def get_library_assets(self, libraryId):
        if libraryId == self.upload_device_id:
            return self.api.searchAssets(deviceId = self.upload_device_id)
        return self.api.searchAssets(libraryId = libraryId)

    def get_asset_library_name(self, asset, libraries):
        """
        bit of a hack, but w/e
        """
        if asset.get("libraryId", None) is not None:
            return libraries[asset["libraryId"]]["name"]
        return "upload"
            

    def find_all_single_stored_assets(self, printMatches=False):
        """
        Find all assets that are only present in a single library.
        """
        single_stored_assets = []
        libraries = self.get_all_libraries()
        for libraryId, library in self.get_all_libraries().items():
            for asset in self.get_library_assets(libraryId):
                if asset.get("duplicateId", None) is None:
                    single_stored_assets.append((library["name"], asset))
                    if printMatches:
                        print(f"{library['name']},{asset['id']},{asset['exifInfo']['dateTimeOriginal']},{asset['originalPath']}")
        return single_stored_assets

    def find_assets_not_in_library(self, targetLibraryId):
        if not targetLibraryId:
            return []
        assets_not_in_library = []
        libraries = self.get_all_libraries()
        for libraryId, library in self.get_all_libraries().items():
            if libraryId == targetLibraryId:
                continue
            for asset in self.get_library_assets(libraryId):
                if asset.get("duplicateId", None) is None:
                    assets_not_in_library.append(asset)
                # maybe right, but asset["libraryId"] is deprecated
                elif libraryId not in [asset["libraryId"] for asset in self.dups(asset)]:
                    assets_not_in_library.append(asset)
        return assets_not_in_library

    def db(self, query, env_file=".env", index=None):
        """
        what an ugly mess.

        docker exec -it immich_postgres psql --dbname=$(grep DB_DATABASE_NAME .env|cut -d= -f2) --username=$(grep DB_USERNAME .env |cut -d= -f2) -c "update asset_faces set \"personId\" = '4d936cdd-584d-4372-a67c-041de8a3f64c' where \"id\" = 'aee38fad-af20-4ba8-a8aa-bae55a7306f8';"

        FIXED:
        docker exec -it immich_postgres
        psql
        --dbname=$(grep DB_DATABASE_NAME .env|cut -d= -f2)
        --username=$(grep DB_USERNAME .env |cut -d= -f2)
        -c
        VARIABLE:
        "update asset_faces set \"personId\" = '4d936cdd-584d-4372-a67c-041de8a3f64c' where \"id\" = 'aee38fad-af20-4ba8-a8aa-bae55a7306f8';"
        """

        db_database_name = ""
        db_username = ""
        with open(env_file, "r") as ENV:
            for line in ENV.readlines():
                if line.startswith("DB_DATABASE_NAME"):
                    db_database_name = line.split("=")[1].strip()
                elif line.startswith("DB_USERNAME"):
                    db_username = line.split("=")[1].strip()

        queryfile = tempfile.mktemp()
        with open(queryfile, "w") as QUERYFILE:
            QUERYFILE.write(query)
            QUERYFILE.write("\n")
        cmd = f"docker cp {queryfile} immich_postgres:/query"
        proc = Popen(cmd.split(), stdout=PIPE, stderr=PIPE)
        stdout, stderr = proc.communicate()
        if proc.returncode != 0:
            print(f"Error {proc.returncode} copying {queryfile} to immich_postgres:/query: {stderr}")
            return ""
        os.unlink(queryfile)
        #cmd = f"docker exec -it immich_postgres psql --dbname={db_database_name} --username={db_username} -c \"{query}\""
        proc = Popen(["./db_runner"], stdout=PIPE, stderr=PIPE)
        stdout, stderr = proc.communicate()
        if proc.returncode != 0:
            print(f"Error {proc.returncode} execing database call: {str(stderr, encoding='utf-8')}")
            return []
        #with open("stdout", "r") as STDOUT:
        #    return STDOUT.read()
        #print(stdout)
        keys = []
        rows = defaultdict(list)
        stdout = str(stdout, encoding="utf-8")
        if stdout.startswith("UPDATE"):
            val = stdout.strip().split()[-1]
            return {"all": [{"UPDATE": val}]}
        for line in stdout.splitlines():
            if "-----" in line:
                continue
            if line.startswith("(") and line.endswith(")"):
                continue
            if not line.strip():
                continue
            if not keys:
                keys = [k.strip() for k in line.split("|")]
            else:
                row = dict((k, v) for k, v in zip(keys, (val.strip() for val in line.split("|"))))
                rows["all" if index is None else row[index]].append(row)
        return rows

    def archive_assets(self, assetIds: list):
        if not assetIds:
            return
        return self.api.updateAssets(assetIds, isArchived=True)

    def update_asset_person(self, asset_id: str, existing_name: str, updated_name: str):
        existing_id = self.find_person_id(existing_name)
        updated_id = self.find_person_id(updated_name)
        rows = self.db(f"""select * from asset_faces where "assetId" = '{asset_id}';""", index="personId")
        if existing_id not in rows:
            return 0
        count = 0
        for row in rows[existing_id]:
            result = self.db(f"""update asset_faces set "personId" = '{updated_id}' where "id" = '{row["id"]}';""")
            if result:
                count += 1
        return count

    def pfx(self, path):
        return "/".join(path.split("/")[:3])

    def best_copy(self, assets):
        scores = [0] * len(assets)
        max_size = 0
        max_size_idx = []
        max_dims = 0
        max_dims_idx = []
        for idx, asset in enumerate(assets):
            asset_file_size = asset.get("exifInfo", {}).get("fileSizeInbyte", 0)
            if asset_file_size > max_size:
                max_size = asset_file_size
                max_size_idx = [idx]
            elif asset_file_size == max_size:
                max_size_idx.append(idx)
            asset_width = int(asset.get("exifInfo", {}).get("exifImageWidth", 0))
            asset_height = int(asset.get("exifInfo", {}).get("exifImageHeight", 0))
            asset_dims = asset_width * asset_height
            if asset_dims > max_dims:
                max_dims = asset_dims
                max_dims_idx = [idx]
            elif asset_dims == max_dims:
                max_dims_idx.append(idx)
        for idx in max_size_idx:
            scores[idx] += 2
        for idx in max_dims_idx:
            scores[idx] += 8

        max_score = max(scores)
        max_scorers = [assets[n] for n in range(len(assets)) if scores[n] == max_score]
        if any(ass["visibility"] == "timeline" for ass in max_scorers):
            for ass in max_scorers:
                if ass["visibility"] == "timeline":
                    return ass
        for idx, score in enumerate(scores):
            if score == max_score:
                return assets[idx]
        return assets[0]

    def dedup(self, *args):
        dups = [dup["assets"] for dup in self.api.dups()]
        for dup_set in dups:
            blessed_prefix = None
            for prefix in self.path_prefix_priority_list:
                if any(self.pfx(ass["originalPath"]) == prefix for ass in dup_set):
                    blessed_prefix = prefix
                    break
            if not blessed_prefix:
                # wtf
                continue
            to_archive = [ass["id"] for ass in dup_set if ass["visibility"] == "timeline" and self.pfx(ass["originalPath"]) != blessed_prefix]
            if to_archive:
                print(f"Archiving {len(to_archive)} dups of blessed copy in {blessed_prefix})")
                self.api.updateAssets(to_archive, visibility="archive")
            blessed_copies = [ass for ass in dup_set if self.pfx(ass["originalPath"]) == blessed_prefix]
            if len(blessed_copies) > 1:
                keeper = self.best_copy(blessed_copies)
                if keeper["visibility"] == "archive":
                    # oopsie
                    print(f"Restoring keeper {keeper['id']} to the timeline")
                to_archive = [ass["id"] for ass in dup_set if ass != keeper]
                if to_archive:
                    print(f"Archiving {len(to_archive)} dups of best copy in {blessed_prefix}: {keeper['id']}")
                    self.api.updateAssets(to_archive, visibility="archive")
                    self.api.updateAssets([keeper["id"]], visibility="timeline")


    # this does not protect precious photos enough for deletion
    # but it should be fine for archiving dups from the timeline
    path_prefix_priority_list = [
        '/photos/wedding', 
        '/photos/undisposed', 
        '/photos/sarah', 
        '/dropbox/may-mays_and_gifs', 
        '/photos/misc', 
        '/photos/img', 
        '/photos/digital', 
        '/photos/2007-01 bink Pictures', 
        '/photos/2021-06-15 photos', 
        '/photos/kittens', 
        '/photos/blackhat_2010', 
        '/photos/STScI-01G7ETPF7DVBJAC42JR5N6EQRH.png', 
        '/photos/lighthouse', 
        '/photos/LIT-18616-03-73', 
        '/photos/DEF CON 29 pictures', 
        '/photos/rochester', 
        '/photos/hawks.png', 
        '/photos/ac', 
        '/photos/masonlake', 
        '/photos/bp98-positron', 
        '/photos/headshot candidates', 
        '/photos/enhjr0thbday', 
        '/photos/van', 
        '/photos/osprey.jpg', 
        '/photos/win Pictures', 
        '/photos/sign', 
        '/photos/tord', 
        '/photos/space', 
        '/photos/home', 
        '/photos/shadok-party', 
        '/photos/rock', 
        '/photos/photos', 
        '/photos/OneDrive 2023-10-17', 
        '/photos/vacation', 
        '/photos/xj', 
        '/photos/DEF CON 30 pictures', 
        '/photos/office', 
        '/photos/nyc', 
        '/photos/corner', 
        '/photos/calendar photos from sarah November 2024', 
        '/photos/f150.jpg', 
        '/photos/DC30', 
        '/photos/home_infra', 
        '/photos/old panasonic card', 
        '/photos/spiral_colors.jpg', 
        '/photos/dilbert', 
        '/photos/olympic', 
        '/photos/orcas', 
        '/photos/kitties', 
        '/photos/PICTURES', 
        '/photos/kubernetes.svg', 
        '/photos/Holm ink monsters', 
        '/photos/Universal 2018', 
        '/photos/Max Encompass 2013', 
        '/photos/Max Innotab photos 2015', 
        '/photos/Max Encompass 2014', 
        '/photos/rosen',
        'upload/upload/d8fbf34b-0e56-43dd-87b3-b7774f6b3f3b', 
        '/photos/gopro', 
        '/photos/disk1 photos', 
        '/photos/GooglePhotos', 
        '/photos/rescued_from_aperture', 
        '/photos/downloaded photo zips', 
        '/photos/from iphone', 
        '/photos/PhotoStream', 
        '/photos/icloud', 
        '/photos/photos 2017-08-31', 
        '/photos/fuck you apple', 
        '/photos/icloud backup', 
        '/photos/iphone_photos_20180103 PARTIAL you suck windows', 
        '/photos/iphone_photos_partial_backup_20180103', 
        '/dropbox/Camera Uploads', 
        '/photos/backup', 
    ]



#to_be_archived = []
#for dup in ic.api.dups():
#    dup_set = dup["assets"]
#    if any(ass["originalPath"].startswith("upload") for ass in dup_set):
#        for ass in dup_set:
#            if ass["visibility"] == "archive":
#                continue
#            if ass["originalPath"].startswith("/dropbox"):
#                print(f"Archiving DropBox asset that has a dup in uploads: {ass['id']} ({len(dup_set)} total dups)")
#                to_be_archived.append(ass["id"])
#            elif ass["originalPath"].startswith("/photos/Google"):
#                print(f"Archiving /photos/Google asset that has a dup in uploads: {ass['id']} ({len(dup_set)} total dups)")
#                to_be_archived.append(ass["id"])
#ic.api.updateAssets(to_be_archived, visibility="archive")
#print(f"Updated {len(to_be_archived)} assets")

#    for libraryId, library in ic.get_all_libraries().items():
#        if "dropbox" in library["name"].lower():
#            print(json.dumps(ic.find_assets_not_in_library(libraryId)))
#            return

if __name__ == "__main__":
main()

#for asset in ic.api.getAlbumInfo(ic.find_album_id("maxnoterica"))["assets"]:
#    print(ic.update_asset_person(asset["id"], "Erica", "Max"))

#dest = "/mnt/files/protect"
#album_name = "protect"
#ic.delete_and_remove_album_assets(album_name)
#for asset in ic.api.getAlbumInfo(ic.find_album_id(album_name))["assets"]:
#    true_path = ic.find_true_path(asset["originalPath"])
#    print(f"Copying {true_path} to {dest}")
#    proc = Popen(["cp", true_path, dest], stdout=PIPE, stderr=PIPE)
#    stdout, stderr = proc.communicate()
#    if proc.returncode != 0:
#        raise(Exception(f"Error {proc.returncode} copying {asset['originalPath']}: {stderr}"))
#return 

#goog_year_folders, goog_album_folders = ic.google_folder_assets()
#for asset in (folder_asset for folder, folder_assets in goog_album_folders.items() for folder_asset in folder_assets):
#    print(f"{asset['id']} {asset['originalPath']}")
#for folder, folder_assets in goog_album_folders.items():
#    print(f"removing {len(folder_assets)} assets for path {folder}")
#    print(ic.api.deleteAssets([asset["id"] for asset in folder_assets]))

#print(ic.delete_and_remove_album_assets("hide"))

#print("Fixing up library exclusions")

#patterns = ic.api.getLibrary("e9211d1f-1e7b-4c5f-b14d-bf141f767da6")["exclusionPatterns"]
#for idx, pattern in enumerate(patterns):
#    if pattern.startswith("**/photos"):
#        patterns[idx] = pattern.lstrip("*")
#ic.api.updateLibrary("e9211d1f-1e7b-4c5f-b14d-bf141f767da6", exclusionPatterns=patterns)

#ic.redundant_google_folders()
#ic.verb("Finding redundant google folders")
#for folder in ic.redundant_google_folders():
#    ic.google_folder_to_album(folder)   

#for dup in ic.api.getAssetDuplicates():
#    for asset in dup["assets"]:
#        if asset["id"] == "6a3afcab-f47c-497c-bec5-fb312f129f64":
#            for asset in dup["assets"]:
#                print(asset["originalPath"])

#subs = list(ic.subdirs("photos"))
#for sub, assets in ic.assets_by_subdir("photos").items():
#    print(len(assets), sub)

#ic.find_all_single_stored_assets()
#print(json.dumps(ic.api.getAssetInfo("53eea0ae-8ac2-43c1-932e-89bdb18fd915")))
#print(json.dumps(ic.dups(ic.api.getAssetInfo("53eea0ae-8ac2-43c1-932e-89bdb18fd915"))))
#erica = ic.api.searchPerson("Erica")
#if type(erica) != list:
#    print("Unable to find person object for Erica")
#    return
#ericaId = erica[0]["id"]
#album_assets = []
#for asset in ic.api.searchAssets(personIds = [ericaId]):
#    #if len(list(filter(lambda person: person["id"] == ericaId, asset["people"]))) > 1:
#    #    album_assets.append(asset) 
#    for person in asset["people"]:
#        if person["id"] == ericaId:
#            if len(person["faces"]) > 1:
#                album_assets.append(asset["id"])
#print(f"Found {len(album_assets)} assets with 2 or more Erica faces")
#albumId = "7f95eebe-be5a-4708-8837-be0dcf259986"
#ic.api.addAssetsToAlbum(albumId, album_assets)

#maxwell = ic.api.searchPerson("Max")
#if type(maxwell) != list:
#    print("Unable to find person object for Maxwell")
#    return
#maxwellId = maxwell[0]["id"]

#max_personId = "4d936cdd-584d-4372-a67c-041de8a3f64c"
#erica_personId = "6c5c4742-3afc-42e0-b0ba-202f510de460"
#ericaerica_albumId = "7f95eebe-be5a-4708-8837-be0dcf259986"

#for asset in ic.album_assets(ericaerica_albumId):
#    rows = ic.db(f"""select * from asset_faces where "assetId" = '{asset["id"]}';""", index="personId")
#    if len(rows[erica_personId]) != 2:
#        print(f'Found {len(rows[erica_personId])} faces assigned to Erica in asset {asset["id"]}, not fixing')
#        continue

#    # their regular seats at the kitchen table mean Max is more frequently on the right,
#    # and I _think_ that means Max is more likely to be the second face tagged as Erica.
#    # Doesn't make much difference anyway.

#    asset_face_to_change = rows[erica_personId][-1]

#    print(f'Changing asset_faces id {asset_face_to_change["id"]} from personId {asset_face_to_change["personId"]} to {max_personId}')
#    result = ic.db(f"""update asset_faces set "personId" = '{max_personId}' where "id" = '{asset_face_to_change["id"]}';""")
#    print(result)
#    print(f'Removing asset {asset["id"]} from album {ericaerica_albumId}')
#    ic.api.removeAssetFromAlbum(ericaerica_albumId, asset["id"])

#print(ic.db("""select * from asset_faces where "id" = 'aee38fad-af20-4ba8-a8aa-bae55a7306f8';""", index="assetId"))
#print(ic.db("select count(*) from assets;"))

ic = ImmichCli()

for dup_set in (dup["assets"] for dup in ic.api.dups()):
    vis = [ass for ass in dup_set if ass["visibility"] == "timeline"]
    vis_paths = ["/".join(ass["originalPath"].split("/")[:3]) for ass in vis]
    if len(set(vis_paths)) <2:
        continue
    vis_paths.sort()
    print(vis_paths)
count = 0
for dup_set in (dup["assets"] for dup in ic.api.dups()):
    if all(ass["visibility"] == "archive" for ass in dup_set):
        count += 1
        print(f"What are we even doing here, they are all archived: {[ass['id'] for ass in dup_set]}") 
print(f"{count} duplicate sets that are all achived")
for dup_set in (dup["assets"] for dup in ic.api.dups()):
    if all(ass["visibility"] == "archive" for ass in dup_set):
        ic.api.updateAssets([ass["id"] for ass in dup_set], visibility="timeline")
