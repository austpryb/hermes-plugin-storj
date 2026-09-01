"""Storj uplink-c bindings via ctypes.

Python port of the OpenClaw plugin's koffi bindings. Handle types are opaque
one-field structs passed by pointer; result structs are returned *by value* and
carry either a payload pointer or an ``UplinkError *``.

Every result struct that owns heap memory is released through its matching
``uplink_free_*`` function before returning, including on the error paths.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import sys
import threading
from ctypes import (
    POINTER,
    Structure,
    byref,
    c_bool,
    c_char,
    c_char_p,
    c_int32,
    c_int64,
    c_size_t,
    c_void_p,
)
from pathlib import Path
from typing import Any

__all__ = ["StorjClient", "StorjError", "find_library", "library_available"]


# ---------------------------------------------------------------------------
# Struct definitions (mirrors uplink_definitions.h)
# ---------------------------------------------------------------------------


class UplinkAccess(Structure):
    _fields_ = [("_handle", c_size_t)]


class UplinkProject(Structure):
    _fields_ = [("_handle", c_size_t)]


class UplinkDownload(Structure):
    _fields_ = [("_handle", c_size_t)]


class UplinkUpload(Structure):
    _fields_ = [("_handle", c_size_t)]


class UplinkBucketIterator(Structure):
    _fields_ = [("_handle", c_size_t)]


class UplinkObjectIterator(Structure):
    _fields_ = [("_handle", c_size_t)]


class UplinkError(Structure):
    _fields_ = [("code", c_int32), ("message", c_char_p)]


class UplinkBucket(Structure):
    _fields_ = [("name", c_char_p), ("created", c_int64)]


class UplinkSystemMetadata(Structure):
    _fields_ = [
        ("created", c_int64),
        ("expires", c_int64),
        ("content_length", c_int64),
    ]


class UplinkCustomMetadataEntry(Structure):
    _fields_ = [
        ("key", c_char_p),
        ("key_length", c_size_t),
        ("value", c_char_p),
        ("value_length", c_size_t),
    ]


class UplinkCustomMetadata(Structure):
    _fields_ = [
        ("entries", POINTER(UplinkCustomMetadataEntry)),
        ("count", c_size_t),
    ]


class UplinkObject(Structure):
    _fields_ = [
        ("key", c_char_p),
        ("is_prefix", c_bool),
        ("system", UplinkSystemMetadata),
        ("custom", UplinkCustomMetadata),
    ]


class UplinkListObjectsOptions(Structure):
    _fields_ = [
        ("prefix", c_char_p),
        ("cursor", c_char_p),
        ("recursive", c_bool),
        ("system", c_bool),
        ("custom", c_bool),
    ]


class UplinkListBucketsOptions(Structure):
    _fields_ = [("cursor", c_char_p)]


class UplinkPermission(Structure):
    _fields_ = [
        ("allow_download", c_bool),
        ("allow_upload", c_bool),
        ("allow_list", c_bool),
        ("allow_delete", c_bool),
        ("not_before", c_int64),
        ("not_after", c_int64),
    ]


class UplinkSharePrefix(Structure):
    _fields_ = [("bucket", c_char_p), ("prefix", c_char_p)]


class UplinkAccessResult(Structure):
    _fields_ = [("access", POINTER(UplinkAccess)), ("error", POINTER(UplinkError))]


class UplinkProjectResult(Structure):
    _fields_ = [("project", POINTER(UplinkProject)), ("error", POINTER(UplinkError))]


class UplinkBucketResult(Structure):
    _fields_ = [("bucket", POINTER(UplinkBucket)), ("error", POINTER(UplinkError))]


class UplinkObjectResult(Structure):
    _fields_ = [("object", POINTER(UplinkObject)), ("error", POINTER(UplinkError))]


class UplinkUploadResult(Structure):
    _fields_ = [("upload", POINTER(UplinkUpload)), ("error", POINTER(UplinkError))]


class UplinkDownloadResult(Structure):
    _fields_ = [("download", POINTER(UplinkDownload)), ("error", POINTER(UplinkError))]


class UplinkWriteResult(Structure):
    _fields_ = [("bytes_written", c_size_t), ("error", POINTER(UplinkError))]


class UplinkReadResult(Structure):
    _fields_ = [("bytes_read", c_size_t), ("error", POINTER(UplinkError))]


class UplinkStringResult(Structure):
    _fields_ = [("string", c_char_p), ("error", POINTER(UplinkError))]


# ---------------------------------------------------------------------------
# Library loading (lazy — loaded on first StorjClient.open())
# ---------------------------------------------------------------------------

_LIB: ctypes.CDLL | None = None
_LIB_LOCK = threading.Lock()

_LIB_NAMES = {
    "linux": "libuplink.so",
    "darwin": "libuplink.dylib",
    "win32": "libuplink.dll",
}


def find_library(explicit_path: str = "") -> str:
    """Resolve the libuplink shared library path.

    Order: explicit setting -> STORJ_LIBUPLINK_PATH -> plugin native/ dir ->
    the platform's default library name (resolved by the system loader).
    """
    if explicit_path:
        return explicit_path

    env_path = os.environ.get("STORJ_LIBUPLINK_PATH")
    if env_path:
        return env_path

    native = Path(__file__).parent / "native"
    for name in ("libuplink.so", "libuplink.dylib", "libuplink.dll"):
        candidate = native / name
        if candidate.exists():
            return str(candidate)

    found = ctypes.util.find_library("uplink")
    return found or _LIB_NAMES.get(sys.platform, "libuplink.so")


_LOAD_FAILURES: dict[str, bool] = {}


def library_available(explicit_path: str = "") -> bool:
    """True when libuplink can be loaded — used as the tools' check_fn.

    Called on every schema build, so a failed load is remembered per path rather
    than re-attempting dlopen each time.
    """
    if _LIB is not None:
        return True
    key = explicit_path or find_library()
    if _LOAD_FAILURES.get(key):
        return False
    try:
        _load(explicit_path)
        return True
    except OSError:
        _LOAD_FAILURES[key] = True
        return False


def _load(explicit_path: str = "") -> ctypes.CDLL:
    global _LIB
    with _LIB_LOCK:
        if _LIB is not None:
            return _LIB
        path = find_library(explicit_path)
        try:
            lib = ctypes.CDLL(path)
        except OSError as exc:
            raise OSError(
                f"libuplink could not be loaded from {path!r}. Build it from "
                "https://github.com/storj/uplink-c (`make build`), then place it in the "
                "plugin's native/ directory or set STORJ_LIBUPLINK_PATH."
            ) from exc
        _bind(lib)
        _LIB = lib
        return lib


def _bind(lib: ctypes.CDLL) -> None:
    """Declare argtypes/restypes. Wrong or missing declarations segfault."""
    sig = {
        # Access
        "uplink_parse_access": ([c_char_p], UplinkAccessResult),
        "uplink_access_serialize": ([POINTER(UplinkAccess)], UplinkStringResult),
        "uplink_access_share": (
            [
                POINTER(UplinkAccess),
                UplinkPermission,
                POINTER(UplinkSharePrefix),
                c_int64,  # GoInt
            ],
            UplinkAccessResult,
        ),
        "uplink_free_access_result": ([UplinkAccessResult], None),
        # Project
        "uplink_open_project": ([POINTER(UplinkAccess)], UplinkProjectResult),
        "uplink_close_project": ([POINTER(UplinkProject)], POINTER(UplinkError)),
        "uplink_free_project_result": ([UplinkProjectResult], None),
        # Buckets
        "uplink_ensure_bucket": (
            [POINTER(UplinkProject), c_char_p],
            UplinkBucketResult,
        ),
        "uplink_delete_bucket": (
            [POINTER(UplinkProject), c_char_p],
            UplinkBucketResult,
        ),
        "uplink_list_buckets": (
            [POINTER(UplinkProject), POINTER(UplinkListBucketsOptions)],
            POINTER(UplinkBucketIterator),
        ),
        "uplink_bucket_iterator_next": ([POINTER(UplinkBucketIterator)], c_bool),
        "uplink_bucket_iterator_item": (
            [POINTER(UplinkBucketIterator)],
            POINTER(UplinkBucket),
        ),
        "uplink_bucket_iterator_err": (
            [POINTER(UplinkBucketIterator)],
            POINTER(UplinkError),
        ),
        "uplink_free_bucket_iterator": ([POINTER(UplinkBucketIterator)], None),
        "uplink_free_bucket_result": ([UplinkBucketResult], None),
        "uplink_free_bucket": ([POINTER(UplinkBucket)], None),
        # Objects
        "uplink_stat_object": (
            [POINTER(UplinkProject), c_char_p, c_char_p],
            UplinkObjectResult,
        ),
        "uplink_delete_object": (
            [POINTER(UplinkProject), c_char_p, c_char_p],
            UplinkObjectResult,
        ),
        "uplink_list_objects": (
            [POINTER(UplinkProject), c_char_p, POINTER(UplinkListObjectsOptions)],
            POINTER(UplinkObjectIterator),
        ),
        "uplink_object_iterator_next": ([POINTER(UplinkObjectIterator)], c_bool),
        "uplink_object_iterator_item": (
            [POINTER(UplinkObjectIterator)],
            POINTER(UplinkObject),
        ),
        "uplink_object_iterator_err": (
            [POINTER(UplinkObjectIterator)],
            POINTER(UplinkError),
        ),
        "uplink_free_object_iterator": ([POINTER(UplinkObjectIterator)], None),
        "uplink_free_object_result": ([UplinkObjectResult], None),
        "uplink_free_object": ([POINTER(UplinkObject)], None),
        # Upload
        "uplink_upload_object": (
            [POINTER(UplinkProject), c_char_p, c_char_p, c_void_p],
            UplinkUploadResult,
        ),
        "uplink_upload_write": (
            [POINTER(UplinkUpload), c_void_p, c_size_t],
            UplinkWriteResult,
        ),
        "uplink_upload_commit": ([POINTER(UplinkUpload)], POINTER(UplinkError)),
        "uplink_upload_abort": ([POINTER(UplinkUpload)], POINTER(UplinkError)),
        "uplink_free_upload_result": ([UplinkUploadResult], None),
        "uplink_free_write_result": ([UplinkWriteResult], None),
        # Download
        "uplink_download_object": (
            [POINTER(UplinkProject), c_char_p, c_char_p, c_void_p],
            UplinkDownloadResult,
        ),
        "uplink_download_read": (
            [POINTER(UplinkDownload), c_void_p, c_size_t],
            UplinkReadResult,
        ),
        "uplink_close_download": ([POINTER(UplinkDownload)], POINTER(UplinkError)),
        "uplink_free_download_result": ([UplinkDownloadResult], None),
        "uplink_free_read_result": ([UplinkReadResult], None),
        # Free
        "uplink_free_string_result": ([UplinkStringResult], None),
        "uplink_free_error": ([POINTER(UplinkError)], None),
    }
    for name, (argtypes, restype) in sig.items():
        fn = getattr(lib, name)
        fn.argtypes = argtypes
        fn.restype = restype


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


#: Streaming chunk size for uploads and downloads.
CHUNK_SIZE = 1024 * 1024

#: uplink-c reports end-of-stream as an UplinkError whose code is C's EOF (-1)
#: and whose message is NULL — see mallocError() in uplink-c/error.go.
UPLINK_EOF = -1


class StorjError(Exception):
    """An error returned by uplink-c, carrying its UPLINK_ERROR_* code."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _decode(value: bytes | None) -> str:
    return value.decode("utf-8", "replace") if value else ""


def _error_from(err_ptr, fallback: str) -> StorjError:
    """Build a StorjError from an UplinkError * without freeing it."""
    if not err_ptr:
        return StorjError(0, fallback)
    err = err_ptr.contents
    return StorjError(err.code, _decode(err.message) or fallback)


# ---------------------------------------------------------------------------
# High-level client
# ---------------------------------------------------------------------------


class StorjClient:
    """A parsed access grant plus an open project handle."""

    def __init__(self, lib, access_result, project_ptr):
        self._lib = lib
        self._access_result = access_result
        self._access = access_result.access
        self._project = project_ptr

    # -- lifecycle --

    @classmethod
    def open(cls, access_grant: str, libuplink_path: str = "") -> StorjClient:
        lib = _load(libuplink_path)

        access_result = lib.uplink_parse_access(access_grant.encode("utf-8"))
        if access_result.error:
            exc = _error_from(access_result.error, "Failed to parse access grant")
            lib.uplink_free_access_result(access_result)
            raise exc

        project_result = lib.uplink_open_project(access_result.access)
        if project_result.error:
            exc = _error_from(project_result.error, "Failed to open project")
            lib.uplink_free_project_result(project_result)
            lib.uplink_free_access_result(access_result)
            raise exc

        return cls(lib, access_result, project_result.project)

    def close(self) -> None:
        if self._project:
            err_ptr = self._lib.uplink_close_project(self._project)
            self._project = None
            if err_ptr:
                self._lib.uplink_free_error(err_ptr)
        if self._access_result is not None:
            self._lib.uplink_free_access_result(self._access_result)
            self._access_result = None
            self._access = None

    def __enter__(self) -> StorjClient:
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # -- buckets --

    def list_buckets(self) -> list[dict[str, Any]]:
        lib = self._lib
        options = UplinkListBucketsOptions(cursor=None)
        it = lib.uplink_list_buckets(self._project, byref(options))
        buckets: list[dict[str, Any]] = []
        try:
            while lib.uplink_bucket_iterator_next(it):
                b_ptr = lib.uplink_bucket_iterator_item(it)
                if b_ptr:
                    b = b_ptr.contents
                    buckets.append({"name": _decode(b.name), "created": int(b.created)})
                    lib.uplink_free_bucket(b_ptr)
            err_ptr = lib.uplink_bucket_iterator_err(it)
            if err_ptr:
                exc = _error_from(err_ptr, "Bucket list error")
                lib.uplink_free_error(err_ptr)
                if exc.code != 0:
                    raise exc
        finally:
            lib.uplink_free_bucket_iterator(it)
        return buckets

    def create_bucket(self, name: str) -> dict[str, Any]:
        lib = self._lib
        result = lib.uplink_ensure_bucket(self._project, name.encode("utf-8"))
        if result.error:
            exc = _error_from(result.error, "Failed to create bucket")
            lib.uplink_free_bucket_result(result)
            raise exc
        bucket = result.bucket.contents
        info = {"name": _decode(bucket.name), "created": int(bucket.created)}
        lib.uplink_free_bucket_result(result)
        return info

    def delete_bucket(self, name: str) -> None:
        lib = self._lib
        result = lib.uplink_delete_bucket(self._project, name.encode("utf-8"))
        if result.error:
            exc = _error_from(result.error, "Failed to delete bucket")
            lib.uplink_free_bucket_result(result)
            raise exc
        lib.uplink_free_bucket_result(result)

    # -- objects --

    @staticmethod
    def _object_info(obj: UplinkObject) -> dict[str, Any]:
        return {
            "key": _decode(obj.key),
            "is_prefix": bool(obj.is_prefix),
            "content_length": int(obj.system.content_length),
            "created": int(obj.system.created),
            "expires": int(obj.system.expires),
        }

    def list_objects(
        self,
        bucket: str,
        prefix: str | None = None,
        recursive: bool = True,
    ) -> list[dict[str, Any]]:
        lib = self._lib
        options = UplinkListObjectsOptions(
            prefix=prefix.encode("utf-8") if prefix else None,
            cursor=None,
            recursive=recursive,
            system=True,
            custom=False,
        )
        it = lib.uplink_list_objects(self._project, bucket.encode("utf-8"), byref(options))
        objects: list[dict[str, Any]] = []
        try:
            while lib.uplink_object_iterator_next(it):
                obj_ptr = lib.uplink_object_iterator_item(it)
                if obj_ptr:
                    objects.append(self._object_info(obj_ptr.contents))
                    lib.uplink_free_object(obj_ptr)
            err_ptr = lib.uplink_object_iterator_err(it)
            if err_ptr:
                exc = _error_from(err_ptr, "Object list error")
                lib.uplink_free_error(err_ptr)
                if exc.code != 0:
                    raise exc
        finally:
            lib.uplink_free_object_iterator(it)
        return objects

    def stat_object(self, bucket: str, key: str) -> dict[str, Any]:
        lib = self._lib
        result = lib.uplink_stat_object(self._project, bucket.encode("utf-8"), key.encode("utf-8"))
        if result.error:
            exc = _error_from(result.error, "Object not found")
            lib.uplink_free_object_result(result)
            raise exc
        info = self._object_info(result.object.contents)
        lib.uplink_free_object_result(result)
        return info

    def delete_object(self, bucket: str, key: str) -> None:
        lib = self._lib
        result = lib.uplink_delete_object(
            self._project, bucket.encode("utf-8"), key.encode("utf-8")
        )
        if result.error:
            exc = _error_from(result.error, "Failed to delete object")
            lib.uplink_free_object_result(result)
            raise exc
        lib.uplink_free_object_result(result)

    # -- upload / download --

    def _write_all(self, upload, buf, length: int) -> None:
        """Write `length` bytes of `buf` to an open upload, looping on short writes."""
        lib = self._lib
        offset = 0
        base = ctypes.addressof(buf)
        while offset < length:
            write = lib.uplink_upload_write(upload, c_void_p(base + offset), length - offset)
            written = int(write.bytes_written)
            error = _error_from(write.error, "Write failed") if write.error else None
            lib.uplink_free_write_result(write)
            if error is not None:
                raise error
            if written == 0:
                raise StorjError(0, "Upload stalled: uplink accepted 0 bytes")
            offset += written

    def _finish_upload(self, upload) -> None:
        lib = self._lib
        err_ptr = lib.uplink_upload_commit(upload)
        if err_ptr:
            error = _error_from(err_ptr, "Failed to commit upload")
            lib.uplink_free_error(err_ptr)
            if error.code != 0:
                raise error

    def _open_upload(self, bucket: str, key: str):
        lib = self._lib
        result = lib.uplink_upload_object(
            self._project, bucket.encode("utf-8"), key.encode("utf-8"), None
        )
        if result.error:
            error = _error_from(result.error, "Failed to start upload")
            lib.uplink_free_upload_result(result)
            raise error
        return result

    def upload_bytes(self, bucket: str, key: str, data: bytes) -> dict[str, Any]:
        """Upload an in-memory buffer. Prefer upload_file() for anything large."""
        lib = self._lib
        result = self._open_upload(bucket, key)
        upload = result.upload
        try:
            if data:
                buf = (c_char * len(data)).from_buffer_copy(data)
                self._write_all(upload, buf, len(data))
            self._finish_upload(upload)
        except BaseException:
            self._abort(upload)
            raise
        finally:
            lib.uplink_free_upload_result(result)
        return {"bucket": bucket, "key": key, "content_length": len(data)}

    def upload_file(
        self, bucket: str, key: str, path: Path, chunk_size: int = CHUNK_SIZE
    ) -> dict[str, Any]:
        """Stream a local file to Storj without holding it all in memory."""
        lib = self._lib
        result = self._open_upload(bucket, key)
        upload = result.upload
        total = 0
        buf = (c_char * chunk_size)()
        try:
            with open(path, "rb") as handle:
                while True:
                    chunk = handle.readinto(buf)
                    if not chunk:
                        break
                    self._write_all(upload, buf, chunk)
                    total += chunk
            self._finish_upload(upload)
        except BaseException:
            self._abort(upload)
            raise
        finally:
            lib.uplink_free_upload_result(result)
        return {"bucket": bucket, "key": key, "content_length": total}

    def _abort(self, upload) -> None:
        err_ptr = self._lib.uplink_upload_abort(upload)
        if err_ptr:
            self._lib.uplink_free_error(err_ptr)

    def _open_download(self, bucket: str, key: str):
        lib = self._lib
        result = lib.uplink_download_object(
            self._project, bucket.encode("utf-8"), key.encode("utf-8"), None
        )
        if result.error:
            error = _error_from(result.error, "Failed to start download")
            lib.uplink_free_download_result(result)
            raise error
        return result

    def _stream_download(self, bucket: str, key: str, sink, max_bytes: int = 0) -> int:
        """Read an object in chunks, handing each to `sink`. Returns total bytes."""
        lib = self._lib
        result = self._open_download(bucket, key)
        download = result.download
        buf = (c_char * CHUNK_SIZE)()
        pointer = ctypes.cast(buf, c_void_p)
        total = 0
        try:
            while True:
                read = lib.uplink_download_read(download, pointer, CHUNK_SIZE)
                count = int(read.bytes_read)
                eof = False
                failure: StorjError | None = None
                if read.error:
                    candidate = _error_from(read.error, "Download read failed")
                    if candidate.code in (UPLINK_EOF, 0) or "EOF" in candidate.message:
                        eof = True
                    else:
                        failure = candidate
                lib.uplink_free_read_result(read)

                if count > 0:
                    total += count
                    if max_bytes and total > max_bytes:
                        raise StorjError(
                            0,
                            f"Object exceeds max_download_bytes ({max_bytes} bytes). Raise the "
                            "plugin setting or fetch it with the uplink CLI.",
                        )
                    sink(buf.raw[:count])

                if failure is not None:
                    raise failure
                if eof or count == 0:
                    break
        finally:
            err_ptr = lib.uplink_close_download(download)
            if err_ptr:
                lib.uplink_free_error(err_ptr)
            lib.uplink_free_download_result(result)
        return total

    def download_bytes(self, bucket: str, key: str, max_bytes: int = 0) -> bytes:
        """Download an object into memory. Prefer download_to_file() for large ones."""
        chunks: list[bytes] = []
        self._stream_download(bucket, key, chunks.append, max_bytes=max_bytes)
        return b"".join(chunks)

    def download_to_file(self, bucket: str, key: str, path: Path, max_bytes: int = 0) -> int:
        """Stream an object straight to disk. Returns the number of bytes written.

        The object is written to a sibling `.part` file and renamed on success, so
        a failed download never leaves a truncated file at the destination.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_name(path.name + ".part")
        try:
            with open(partial, "wb") as handle:
                total = self._stream_download(bucket, key, handle.write, max_bytes=max_bytes)
            partial.replace(path)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
        return total

    # -- share --

    def create_share_grant(
        self,
        bucket: str,
        prefix: str = "",
        allow_download: bool = True,
        allow_list: bool = True,
        allow_upload: bool = False,
        allow_delete: bool = False,
        not_before: int = 0,
        not_after: int = 0,
    ) -> str:
        lib = self._lib
        permission = UplinkPermission(
            allow_download=allow_download,
            allow_upload=allow_upload,
            allow_list=allow_list,
            allow_delete=allow_delete,
            not_before=not_before,
            not_after=not_after,
        )
        prefixes = (UplinkSharePrefix * 1)(
            UplinkSharePrefix(bucket=bucket.encode("utf-8"), prefix=prefix.encode("utf-8"))
        )

        share = lib.uplink_access_share(self._access, permission, prefixes, 1)
        if share.error:
            exc = _error_from(share.error, "Failed to create share")
            lib.uplink_free_access_result(share)
            raise exc

        serialized = lib.uplink_access_serialize(share.access)
        if serialized.error:
            exc = _error_from(serialized.error, "Failed to serialize access")
            lib.uplink_free_string_result(serialized)
            lib.uplink_free_access_result(share)
            raise exc

        grant = _decode(serialized.string)
        lib.uplink_free_string_result(serialized)
        lib.uplink_free_access_result(share)
        return grant
