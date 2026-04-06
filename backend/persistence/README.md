# Grinta Storage Module

The storage module provides different storage options for file operations in Grinta, used for storing events, settings and other metadata. This module implements a common interface (`FileStore`) that allows for interchangeable storage backends.

**Usage:**

```python

store = ...

# Write, read, list, and delete operations
store.write("example.txt", "Hello, world!")
content = store.read("example.txt")
files = store.list("/")
store.delete("example.txt")
```

## Available Storage Options

### 1. Local File Storage (`local`)

Local file storage saves files to the local filesystem.

**Environment Variables:**

- None specific to this storage option
- Files are stored under `local_data_root` in `AppConfig`

### 2. In-Memory Storage (`memory`)

In-memory storage keeps files in memory, which is useful for testing or temporary storage.

**Environment Variables:**

- None

### 3. Amazon S3 Storage (`s3`)

S3 storage uses Amazon S3 or compatible services for file storage.

**Environment Variables:**

- The bucket name is specified by `local_data_root` with a fallback to the `AWS_S3_BUCKET` environment variable.
- `AWS_ACCESS_KEY_ID`: Your AWS access key
- `AWS_SECRET_ACCESS_KEY`: Your AWS secret key
- `AWS_S3_ENDPOINT`: Optional custom endpoint for S3-compatible services (Allows overriding the default)
- `AWS_S3_SECURE`: Whether to use HTTPS (default: "true")

### 4. Google Cloud Storage (`google_cloud`)

Google Cloud Storage uses Google Cloud Storage buckets for file storage.

**Environment Variables:**

- The bucket name is specified by `local_data_root` with a fallback to the `GOOGLE_CLOUD_BUCKET_NAME` environment variable.
- `GOOGLE_APPLICATION_CREDENTIALS`: Path to Google Cloud credentials JSON file

## Local-First Behavior

Grinta now uses local-first storage only. Remote webhook forwarding and database-backed file-store adapters were removed to keep persistence predictable for the single-user CLI workflow.

## Configuration

To configure the storage module in App, use the following configuration options:

```toml
[core]
# File store type: "local" or "memory"
file_store = "local"

# Disk root for local file store
local_data_root = "/tmp/file_store"
```
