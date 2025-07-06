#!/usr/bin/env python3

import json
import requests

from urllib.parse import quote

class ImmichApi(object):
    def __init__(self, *args, **kwargs):
        self.dry_run = False
        self.dupsfile = None
        self.url = "http://localhost:2283/api"
        self.env_file = ".env"
        self.headers = {
            "x-api-key": None,
            "accept": "application/json",
            "content-type": "application/json",
        }

        self.dup_cache = []
        self.dups_by_duplicateId = {}

        for k, v in kwargs.items():
            setattr(self, k, v)

        with open(self.env_file, "r") as ENV:
            for line in (l.strip() for l in ENV.readlines()):
                if not line:
                    continue
                if line.startswith("#"):
                    continue
                k, v = (val.strip() for val in line.split("="))
                if k.lower() == "x_api_key":
                    self.headers["x-api-key"] = v

        if self.dupsfile:
            try:
                with open(self.dupsfile, "r") as INFILE:
                    dups = json.loads(INFILE.read())
            except Exception as e:
                print(f"Unable to read json from {self.dupsfile} ({str(e)})")

    def dups(self, asset: dict = None):
        """
        Every set of discovered duplicates.
        Or the set of duplicates discovered for a given asset.
        """
        if not self.dup_cache:
            self.dup_cache = self.getAssetDuplicates()
            self.dups_by_duplicateId = dict((dup_set["duplicateId"], dup_set) for dup_set in self.dup_cache)

        if asset is None:
            return self.dup_cache

        dupid = asset.get("duplicateId", None)
        if dupid not in self.dups_by_duplicateId:
            return []
        return [dup_asset for dup_asset in self.dups_by_duplicateId[dupid]["assets"] if dup_asset != asset]

    def get(self, path: str, body: dict = None, req_headers: dict = None, method: str = "get"):
        headers = self.headers
        if req_headers:
            headers = req_headers
            for k, v in self.headers.items():
                if k not in headers:
                    headers[k] = v
        kwargs = {"headers": headers}
        if body:
            kwargs["json"] = body
        if self.dry_run:
            print(f"dry_run: requests.get({self.url + path}, kwargs: {kwargs})")
            return {}
        method_method = getattr(requests, method)
        resp = method_method(self.url + path, **kwargs)
        if headers["accept"] == "application/json":
            try:
                return resp.json()
            except:
                pass
        return resp

    def fix_path(self, path: str):
        path = path.lstrip("/")        
        if not path.endswith("/"):
            path = path + "/"
        return path

    def getAssetDuplicates(self):
        return self.get("/duplicates")

    def getUniqueOriginalPaths(self):
        return self.get("/view/folder/unique-paths")

    def getAssetsByOriginalPath(self, path: str):
        path = self.fix_path(path)
        return self.get(f"/view/folder?path={quote(path)}")

    def getAssetInfo(self, assetId: str):
        return self.get(f"/assets/{assetId}")

    def deleteAssets(self, ids: list, force: bool = False):
        body = { "ids": ids }
        return self.get(f"/assets", method="delete", req_headers={"Content-Type": "application/json"}, body=body)

    def getAlbums(self, assetId: str = None):
        if assetId is None:
            return self.get("/albums")
        return self.get(f"/albums?assetId={assetId}")

    def getAlbumInfo(self, albumId: str):
        return self.get(f"/albums/{albumId}")

    def createAlbum(self,
        albumName: str,
        albumUsers: list = [{"role": "editor", "userId": "d8fbf34b-0e56-43dd-87b3-b7774f6b3f3b"}],
        assetIds: list = None,
        description: str = None,
    ):
        body = {
            "albumName": albumName,
            "albumUsers": albumUsers,
        }
        if assetIds is not None:
            body["assetIds"] = assetIds
        if description is not None:
            body["description"] = description
        return self.get("/albums", method="post", req_headers={"Content-Type": "application/json"}, body=body)

    def addAssetsToAlbum(self, albumId: str, ids: list, key: str = None):
        body = { "ids": ids }
        if key is not None:
            body["key"] = key
        return self.get(f"/albums/{albumId}/assets", method="put", req_headers={"Content-Type": "application/json"}, body=body)

    def removeAssetFromAlbum(self, albumId: str, assetId: str):
        body = { "ids": [ assetId ] }
        return self.get(f"/albums/{albumId}/assets", method="delete", req_headers={"Content-Type": "application/json"}, body=body)

    def getAllLibraries(self):
        return self.get("/libraries")

    def getLibrary(self, id: str):
        return self.get(f"/libraries/{id}")

    def updateLibrary(self, id: str, exclusionPatterns: list = None, importPaths: list = None, name: str = None):
        body = {}
        if exclusionPatterns is not None:
            body["exclusionPatterns"] = exclusionPatterns
        if importPaths is not None:
            body["importPaths"] = importPaths
        if name is not None:
            body["name"] = name
        return self.get(f"/libraries/{id}", method="put", req_headers={"Content-Type": "application/json"}, body=body)

    def searchPerson(self, name):
        return self.get(f"/search/person?name={name}")

    def searchAssets(self, **kwargs):
        """
        Yields search results until there are no more, than raises StopIteration.
        """
        body = {}
        for k, v in kwargs.items():
            body[k] = v
        if "page" not in body:
            body["page"] = 1
        nextPage = body["page"]
        while nextPage:
            body["page"] = nextPage
            result = self.get("/search/metadata", method="post", req_headers={"Content-Type": "application/json"}, body=body)
            nextPage = result["assets"].get("nextPage", None)
            for asset in result["assets"]["items"]:
                yield asset

    def updateAssets(self, assetIds: list, **kwargs):
        update_allowed_keys = ["dateTimeOriginal", "duplicateId", "visibility", "isFavorite", "latitude", "longitude", "rating"]
        body = {}
        for k, v in kwargs.items():
            if k not in update_allowed_keys:
                raise(Exception("Illegal asset update key: {k}"))
            body[k] = v
        body["ids"] = assetIds
        return self.get(f"/assets", method="put", req_headers={"Content-Type": "application/json"}, body=body)

    def uploads(self):
        return api.searchAssets(deviceId="63ae08d41c982c437c6967d4b885fad35668ad555e810dad676807339af70a7a")
            

def main():
    api = ImmichApi()
    #folders = api.getUniqueOriginalPaths()
    #assets = api.getAssetsByOriginalPath(folders[17])
    #info = api.getAssetInfo(assets[0]["id"])
    #print(json.dumps(info))
    #print(json.dumps(api.getAlbums("9e56cfc0-a893-4b2c-a118-088ca0d54a95")))
    #print(json.dumps(api.getAlbumInfo(api.getAlbums("9e56cfc0-a893-4b2c-a118-088ca0d54a95")[0]["id"])))
    #album = api.createAlbum("foo")
    #print(json.dumps(api.addAssetsToAlbum(album["id"], ids=["9e56cfc0-a893-4b2c-a118-088ca0d54a95"])))
    #libs = api.getAllLibraries()
    #for lib in libs:
    #    if "dropbox" in lib["name"]:
    #        patterns = lib["exclusionPatterns"]
    #        patterns.append("NOT_THERE")
    #        api.updateLibrary(lib["id"], exclusionPatterns = patterns)
    #for album in api.getAlbums():
    #    if album["albumName"] == "OnlyBink":
    #        print(json.dumps(api.getAlbumInfo(album["id"])))
    #print(json.dumps(api.dups()))
    #print(json.dumps(api.getAssetInfo("8435ade9-30fd-4573-bfb6-272f591d5dfb")))
    count = 0
    for result in api.searchAssets(deviceId="63ae08d41c982c437c6967d4b885fad35668ad555e810dad676807339af70a7a"):
        count += 1
        if result.get("duplicateId", None):
            print(result["id"], result["libraryId"] or "upload", result["originalPath"])
            for dup_asset in api.dups(asset=result):
                print(dup_asset["id"], dup_asset["libraryId"] or "upload", dup_asset["originalPath"])
            break

    print(count)

if __name__ == "__main__":
    main()
