# ARM REST API Documentation

## Overview

The Automatic Ripping Machine (ARM) provides a comprehensive REST API that enables external applications—such as mobile apps, web UIs, and automation tools—to interact with ARM programmatically. This API exposes all data rendered by the ARM web interface, allowing developers to build custom frontends or integrate ARM into larger media management workflows.

### Key Features

- **Full Data Access**: Retrieve jobs, tracks, system status, settings, notifications, logs, and history
- **Job Management**: Create, monitor, update, and delete ripping jobs
- **System Control**: Monitor drive status, eject drives, and track system resources
- **Configuration Management**: Read and modify ARM and UI settings
- **Authentication**: Secure access with session-based or API key authentication
- **Pagination**: Efficient data retrieval for large datasets

### Base URL

```
http://your-arm-server:8000/api/v1
```

All endpoints are relative to this base URL. Replace `your-arm-server` with your ARM server's hostname or IP address and `8000` with your configured webserver port.

---

## Authentication

### Authentication Methods

ARM supports three authentication methods for API access:

#### 1. Session Authentication (Browser-based)

When accessing the API through a web browser where you've already logged into the ARM web interface, your session cookie is automatically used for authentication.

**No additional headers required.**

#### 2. Bearer Token Authentication

For programmatic access, use API key authentication by including your API key in the Authorization header:

```http
Authorization: Bearer YOUR_API_KEY
```

**Example:**
```bash
curl -H "Authorization: Bearer abc123xyz" http://localhost:8000/api/v1/jobs
```

#### 3. Query Parameter Authentication

For simple integrations or testing, you can pass the API key as a query parameter:

```http
http://your-arm-server:8000/api/v1/jobs?api_key=YOUR_API_KEY
```

**Note:** This method is less secure and should only be used when headers are not available.

### Getting an API Key

API keys are generated and managed through the ARM user interface:

1. Log into the ARM web interface
2. Navigate to Settings → Users
3. Create or edit a user account
4. Generate or view the API key for that user

### Authentication Required vs. Public Endpoints

| Endpoint | Authentication Required |
|----------|------------------------|
| `/api/v1/jobs/active` | No (Public) |
| `/api/v1/system/status` | No (Public) |
| All other endpoints | Yes |

The active jobs and system status endpoints are intentionally public to allow monitoring dashboards or status pages without authentication.

---

## Response Format

### Success Response

All successful API responses follow this structure:

```json
{
    "success": true,
    "data": { ... },
    "message": "Optional human-readable message"
}
```

For paginated list endpoints:

```json
{
    "success": true,
    "data": {
        "items": [ ... ],
        "pagination": {
            "page": 1,
            "per_page": 20,
            "total": 150,
            "pages": 8,
            "has_prev": false,
            "has_next": true
        }
    }
}
```

### Error Response

Error responses include error details:

```json
{
    "success": false,
    "error": "Descriptive error message",
    "message": "Descriptive error message",
    "errors": ["Optional list of specific errors"]
}
```

### HTTP Status Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 400 | Bad Request (invalid parameters) |
| 401 | Unauthorized (authentication required) |
| 403 | Forbidden (insufficient permissions) |
| 404 | Not Found (resource doesn't exist) |
| 500 | Internal Server Error |

---

## Rate Limiting

**Note:** Rate limiting is planned but not currently implemented. Future versions may include configurable rate limits to prevent abuse.

---

## API Endpoints

### Root

#### GET /

Returns API metadata and available endpoint categories.

**Authentication:** Required

**Response:**

```json
{
    "success": true,
    "data": {
        "name": "ARM API",
        "version": "1.0.0",
        "description": "Automatic Ripping Machine REST API",
        "endpoints": {
            "jobs": "/api/v1/jobs",
            "tracks": "/api/v1/tracks",
            "system": "/api/v1/system",
            "settings": "/api/v1/settings",
            "notifications": "/api/v1/notifications",
            "logs": "/api/v1/logs",
            "history": "/api/v1/history"
        },
        "authentication": "Session or Bearer token required for most endpoints",
        "documentation": "/api/v1/docs"
    }
}
```

---

### Jobs

Jobs represent individual disc ripping operations. Each job contains metadata about the disc, its current status, associated tracks, and configuration.

#### GET /jobs

Retrieve a paginated list of all jobs with optional filtering.

**Authentication:** Required

**Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `page` | integer | No | 1 | Page number (1-based) |
| `per_page` | integer | No | 20 | Items per page (max: 100) |
| `status` | string | No | - | Filter by job status |
| `disctype` | string | No | - | Filter by disc type |
| `video_type` | string | No | - | Filter by video type |
| ` | No | - | Search in jobsearch` | string title |

**Status Values:**
- `active`: Currently active (non-finished) jobs
- `ripping`: Jobs currently ripping
- `transcoding`: Jobs currently transcoding
- `success`: Successfully completed jobs
- `fail`: Failed jobs
- `waiting`: Jobs waiting for user input

**Disc Type Values:**
- `bluray`: Blu-ray discs
- `dvd`: DVD discs
- `music`: Audio CDs
- `data`: Data discs

**Example Request:**

```bash
curl -H "Authorization: Bearer YOUR_KEY" \
     "http://localhost:8000/api/v1/jobs?status=active&page=1&per_page=10"
```

**Example Response:**

```json
{
    "success": true,
    "data": {
        "jobs": [
            {
                "job_id": 123,
                "title": "Movie Title",
                "year": "2023",
                "status": "ripping",
                "status_display": "VIDEO_RIPPING",
                "disctype": "bluray",
                "video_type": "movie",
                "stage": "2/3 - Ripping title 2",
                "progress": 45.5,
                "progress_round": 45,
                "eta": "00:15:30",
                "no_of_titles": 3,
                "start_time": "2024-01-15T10:30:00",
                "stop_time": null,
                "label": "MOVIE_TITLE",
                "imdb_id": "tt1234567",
                "poster_url": "https://image.tmdb.org/poster.jpg",
                "tracks": [...],
                "config": {...}
            }
        ],
        "pagination": {
            "page": 1,
            "per_page": 10,
            "total": 150,
            "pages": 15,
            "has_prev": false,
            "has_next": true
        }
    }
}
```

---

#### GET /jobs/active

Retrieve all currently active (non-finished) jobs.

**Authentication:** Not Required (Public)

**Example Request:**

```bash
curl "http://localhost:8000/api/v1/jobs/active"
```

**Example Response:**

```json
{
    "success": true,
    "data": {
        "jobs": [
            {
                "job_id": 123,
                "title": "Movie Title",
                "label": "MOVIE_TITLE",
                "status": "ripping",
                "status_display": "VIDEO_RIPPING",
                "disctype": "bluray",
                "stage": "2/3 - Ripping title 2",
                "progress": 45.5,
                "progress_round": 45,
                "eta": "00:15:30",
                "no_of_titles": 3,
                "start_time": "2024-01-15T10:30:00",
                "video_type": "movie",
                "imdb_id": "tt1234567",
                "poster_url": "https://image.tmdb.org/poster.jpg"
            }
        ],
        "count": 1
    }
}
```

---

#### GET /jobs/statistics

Retrieve aggregated statistics about jobs.

**Authentication:** Required

**Example Request:**

```bash
curl -H "Authorization: Bearer YOUR_KEY" \
     "http://localhost:8000/api/v1/jobs/statistics"
```

**Example Response:**

```json
{
    "success": true,
    "data": {
        "total": 500,
        "active": 5,
        "success": 450,
        "fail": 45,
        "by_disctype": {
            "bluray": 200,
            "dvd": 250,
            "music": 40,
            "data": 10
        },
        "by_video_type": {
            "movie": 400,
            "series": 50
        }
    }
}
```

---

#### GET /jobs/{job_id}

Retrieve detailed information about a specific job.

**Authentication:** Required

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `job_id` | integer | The unique identifier of the job |

**Example Request:**

```bash
curl -H "Authorization: Bearer YOUR_KEY" \
     "http://localhost:8000/api/v1/jobs/123"
```

**Example Response:**

```json
{
    "success": true,
    "data": {
        "job_id": 123,
        "arm_version": "2.0.0",
        "crc_id": "abc123",
        "logfile": "movie_title_20240115.log",
        "start_time": "2024-01-15T10:30:00",
        "stop_time": null,
        "job_length": "00:45:30",
        "status": "ripping",
        "status_display": "VIDEO_RIPPING",
        "stage": "2/3 - Ripping title 2",
        "no_of_titles": 3,
        "title": "Movie Title",
        "title_auto": "Movie Title",
        "title_manual": null,
        "year": "2023",
        "year_auto": "2023",
        "year_manual": null,
        "video_type": "movie",
        "video_type_auto": "movie",
        "video_type_manual": null,
        "imdb_id": "tt1234567",
        "imdb_id_auto": "tt1234567",
        "imdb_id_manual": null,
        "poster_url": "https://image.tmdb.org/poster.jpg",
        "poster_url_auto": "https://image.tmdb.org/poster.jpg",
        "poster_url_manual": null,
        "devpath": "/dev/sr0",
        "mountpoint": "/mnt/cdrom",
        "hasnicetitle": true,
        "errors": null,
        "disctype": "bluray",
        "label": "MOVIE_TITLE",
        "path": "/mnt/storage/movies/Movie_Title_2023",
        "ejected": false,
        "updated": false,
        "pid": 1234,
        "is_iso": false,
        "manual_start": false,
        "manual_mode": false,
        "progress": 45.5,
        "progress_round": 45,
        "eta": "00:15:30",
        "finished": false,
        "idle": false,
        "ripping": true,
        "tracks": [...],
        "config": {...}
    }
}
```

**Error Response (404):**

```json
{
    "success": false,
    "error": "Job with ID 999 not found",
    "message": "Job with ID 999 not found"
}
```

---

#### DELETE /jobs/{job_id}

Delete a job and its associated tracks and config.

**Authentication:** Required (Admin)

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `job_id` | integer | The unique identifier of the job |

**Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `delete_files` | boolean | No | false | Also delete associated files |

**Example Request:**

```bash
curl -X DELETE \
     -H "Authorization: Bearer YOUR_ADMIN_KEY" \
     "http://localhost:8000/api/v1/jobs/123?delete_files=true"
```

**Example Response:**

```json
{
    "success": true,
    "message": "Job 123 deleted successfully"
}
```

---

#### POST /jobs/{job_id}/abandon

Forcefully terminate a running job.

**Authentication:** Required

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `job_id` | integer | The unique identifier of the job |

**Example Request:**

```bash
curl -X POST \
     -H "Authorization: Bearer YOUR_KEY" \
     "http://localhost:8000/api/v1/jobs/123/abandon"
```

**Example Response:**

```json
{
    "success": true,
    "message": "Job 123 abandoned successfully"
}
```

---

#### GET /jobs/{job_id}/tracks

Retrieve all tracks associated with a specific job.

**Authentication:** Required

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `job_id` | integer | The unique identifier of the job |

**Example Request:**

```bash
curl -H "Authorization: Bearer YOUR_KEY" \
     "http://localhost:8000/api/v1/jobs/123/tracks"
```

**Example Response:**

```json
{
    "success": true,
    "data": {
        "job_id": 123,
        "tracks": [
            {
                "track_id": 1,
                "job_id": 123,
                "track_number": "1",
                "length": 7200,
                "aspect_ratio": "2.39:1",
                "fps": 23.976,
                "main_feature": true,
                "basename": "title01",
                "filename": "title01.mkv",
                "orig_filename": "title01_t00.mkv",
                "new_filename": "Movie_Title_t00.mkv",
                "ripped": true,
                "status": "complete",
                "error": null,
                "source": "bluray",
                "process": true
            },
            {
                "track_id": 2,
                "job_id": 123,
                "track_number": "2",
                "length": 300,
                "aspect_ratio": null,
                "fps": null,
                "main_feature": false,
                "basename": "title02",
                "filename": "title02.mkv",
                "orig_filename": "title02_t01.mkv",
                "new_filename": null,
                "ripped": false,
                "status": "pending",
                "error": null,
                "source": "bluray",
                "process": false
            }
        ]
    }
}
```

---

### Tracks

Tracks represent individual titles/chapters on a disc. Each job can have multiple tracks.

#### GET /tracks

Retrieve a paginated list of all tracks with optional filtering.

**Authentication:** Required

**Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `page` | integer | No | 1 | Page number |
| `per_page` | integer | No | 20 | Items per page (max: 100) |
| `job_id` | integer | No | - | Filter by job ID |
| `ripped` | boolean | No | - | Filter by rip status |
| `main_feature` | boolean | No | - | Filter by main feature flag |

**Example Request:**

```bash
curl -H "Authorization: Bearer YOUR_KEY" \
     "http://localhost:8000/api/v1/tracks?job_id=123&ripped=false"
```

**Example Response:**

```json
{
    "success": true,
    "data": {
        "tracks": [
            {
                "track_id": 1,
                "job_id": 123,
                "track_number": "1",
                "length": 7200,
                "aspect_ratio": "2.39:1",
                "fps": 23.976,
                "main_feature": true,
                "basename": "title01",
                "filename": "title01.mkv",
                "orig_filename": "title01_t00.mkv",
                "new_filename": "Movie_Title_t00.mkv",
                "ripped": true,
                "status": "complete",
                "error": null,
                "source": "bluray",
                "process": true
            }
        ],
        "pagination": {
            "page": 1,
            "per_page": 20,
            "total": 50,
            "pages": 3,
            "has_prev": false,
            "has_next": true
        }
    }
}
```

---

#### GET /tracks/{track_id}

Retrieve detailed information about a specific track.

**Authentication:** Required

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `track_id` | integer | The unique identifier of the track |

**Example Request:**

```bash
curl -H "Authorization: Bearer YOUR_KEY" \
     "http://localhost:8000/api/v1/tracks/1"
```

---

#### PATCH /tracks/{track_id}

Update properties of a specific track.

**Authentication:** Required

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `track_id` | integer | The unique identifier of the track |

**Request Body:**

| Field | Type | Description |
|-------|------|-------------|
| `process` | boolean | Whether to process this track |
| `error` | string | Error message if track failed |

**Example Request:**

```bash
curl -X PATCH \
     -H "Authorization: Bearer YOUR_KEY" \
     -H "Content-Type: application/json" \
     "http://localhost:8000/api/v1/tracks/1" \
     -d '{"process": true}'
```

---

### System

System endpoints provide information about the ARM server, including hardware status and optical drives.

#### GET /system/info

Retrieve server/system information.

**Authentication:** Required

**Example Request:**

```bash
curl -H "Authorization: Bearer YOUR_KEY" \
     "http://localhost:8000/api/v1/system/info"
```

**Example Response:**

```json
{
    "success": true,
    "data": {
        "name": "ARM Server",
        "cpu": "Intel(R) Core(TM) i7-10700K CPU @ 3.80GHz",
        "memory_total_gb": 32.0,
        "python_version": "3.11.0",
        "arm_version": "2.0.0",
        "git_commit": "abc1234"
    }
}
```

---

#### GET /system/status

Retrieve current system status including resource usage.

**Authentication:** Not Required (Public)

**Example Request:**

```bash
curl "http://localhost:8000/api/v1/system/status"
```

**Example Response:**

```json
{
    "success": true,
    "data": {
        "cpu_percent": 45.2,
        "memory_percent": 62.5,
        "memory_used_gb": 20.0,
        "memory_total_gb": 32.0,
        "disk_usage": {
            "total_gb": 2000.0,
            "used_gb": 1200.0,
            "free_gb": 800.0,
            "percent": 60.0
        },
        "active_jobs": 2,
        "drives_ready": 3,
        "timestamp": "2024-01-15T10:30:00"
    }
}
```

---

#### GET /system/drives

Retrieve information about all configured optical drives.

**Authentication:** Required

**Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `include_jobs` | boolean | No | true | Include current job information |

**Example Request:**

```bash
curl -H "Authorization: Bearer YOUR_KEY" \
     "http://localhost:8000/api/v1/system/drives"
```

**Example Response:**

```json
{
    "success": true,
    "data": {
        "drives": [
            {
                "drive_id": 1,
                "name": "Drive 1",
                "description": "Primary Blu-ray Drive",
                "serial_id": "ABCD123456789",
                "maker": "LG",
                "model": "BH16NS55",
                "serial": "ABCD123456789",
                "connection": "SATA",
                "read_cd": true,
                "read_dvd": true,
                "read_bd": true,
                "mount": "/dev/sr0",
                "firmware": "1.00",
                "location": "bay-1",
                "stale": false,
                "mdisc": null,
                "drive_type": "CD/DVD/BluRay",
                "drive_mode": "auto",
                "job_id_current": 123,
                "job_id_previous": 122,
                "tray_status": "DISC_OK",
                "tray_open": false,
                "ready": true,
                "processing": true
            }
        ],
        "count": 2
    }
}
```

---

#### GET /system/drives/{drive_id}

Retrieve detailed information about a specific drive.

**Authentication:** Required

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `drive_id` | integer | The unique identifier of the drive |

---

#### POST /system/drives/{drive_id}/eject

Toggle the eject status of a drive.

**Authentication:** Required

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `drive_id` | integer | The unique identifier of the drive |

**Example Request:**

```bash
curl -X POST \
     -H "Authorization: Bearer YOUR_KEY" \
     "http://localhost:8000/api/v1/system/drives/1/eject"
```

---

### Settings

Settings endpoints allow reading and modifying ARM configuration.

#### GET /settings

Retrieve all ARM configuration settings.

**Authentication:** Required

**Note:** Sensitive values (API keys, passwords, tokens) are hidden and replaced with `<hidden>`.

**Example Request:**

```bash
curl -H "Authorization: Bearer YOUR_KEY" \
     "http://localhost:8000/api/v1/settings"
```

**Example Response:**

```json
{
    "success": true,
    "data": {
        "ARM_NAME": "My ARM",
        "VIDEOTYPE": "auto",
        "MINLENGTH": "300",
        "MAXLENGTH": "99999",
        "RIPMETHOD": "mkv",
        "MAINFEATURE": true,
        "LOGLEVEL": "INFO",
        "LOGPATH": "/mnt/storage/logs/arm",
        "COMPLETED_PATH": "/mnt/storage/movies",
        "TRANSCODE_PATH": "/mnt/storage/transcode",
        "WEBSERVER_PORT": 8000,
        "OMDB_API_KEY": "<hidden>",
        "EMBY_SERVER": "<hidden>",
        ...
    }
}
```

---

#### GET /settings/ui

Retrieve ARM UI configuration settings from database.

**Example Request:**

```bash
curl -H "Authorization: Bearer YOUR_KEY" \
     "http://localhost:8000/api/v1/settings/ui"
```

**Example Response:**

```json
{
    "success": true,
    "data": {
        "id": 1,
        "use_icons": true,
        "save_remote_images": false,
        "bootstrap_skin": "darkly",
        "language": "en",
        "index_refresh": 5,
        "database_limit": 100,
        "notify_refresh": 6500
    }
}
```

---

#### PATCH /settings/ui

Update ARM UI configuration settings.

**Authentication:** Required (Admin)

**Request Body:**

| Field | Type | Description |
|-------|------|-------------|
| `use_icons` | boolean | Use icons in UI |
| `save_remote_images` | boolean | Save remote images locally |
| `bootstrap_skin` | string | Bootstrap theme (e.g., "darkly", "cosmo") |
| `language` | string | Language code |
| `index_refresh` | integer | Index page refresh rate (seconds) |
| `database_limit` | integer | Database entries per page |
| `notify_refresh` | integer | Notification refresh rate (milliseconds) |

**Example Request:**

```bash
curl -X PATCH \
     -H "Authorization: Bearer YOUR_ADMIN_KEY" \
     -H "Content-Type: application/json" \
     "http://localhost:8000/api/v1/settings/ui" \
     -d '{"bootstrap_skin": "darkly", "index_refresh": 10}'
```

---

#### GET /settings/abcde

Retrieve the ABCDE (audio CD ripper) configuration.

**Example Request:**

```bash
curl -H "Authorization: Bearer YOUR_KEY" \
     "http://localhost:8000/api/v1/settings/abcde"
```

---

#### GET /settings/apprise

Retrieve the Apprise notification configuration.

**Note:** Sensitive values are hidden.

**Example Request:**

```bash
curl -H "Authorization: Bearer YOUR_KEY" \
     "http://localhost:8000/api/v1/settings/apprise"
```

---

### Notifications

Notifications provide alerts about job events, system status, and user actions.

#### GET /notifications

Retrieve notifications with optional filtering.

**Authentication:** Required

**Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `page` | integer | No | 1 | Page number |
| `per_page` | integer | No | 20 | Items per page |
| `seen` | boolean | No | - | Filter by seen status |
| `limit` | integer | No | - | Limit to N most recent |

**Example Request:**

```bash
curl -H "Authorization: Bearer YOUR_KEY" \
     "http://localhost:8000/api/v1/notifications?seen=false"
```

**Example Response:**

```json
{
    "success": true,
    "data": {
        "notifications": [
            {
                "id": 1,
                "seen": false,
                "trigger_time": "2024-01-15T10:30:00",
                "dismiss_time": null,
                "title": "Job Complete",
                "message": "Job 123 completed successfully",
                "cleared": false,
                "cleared_time": null
            }
        ],
        "pagination": {...}
    }
}
```

---

#### GET /notifications/unread

Retrieve all unread (unseen) notifications.

**Authentication:** Required

---

#### POST /notifications/{notification_id}/read

Mark a specific notification as seen/read.

**Authentication:** Required

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `notification_id` | integer | The unique identifier of the notification |

---

#### POST /notifications/read-all

Mark all unread notifications as seen.

**Authentication:** Required

**Example Request:**

```bash
curl -X POST \
     -H "Authorization: Bearer YOUR_KEY" \
     "http://localhost:8000/api/v1/notifications/read-all"
```

---

### Logs

Logs endpoints provide access to ARM log files for debugging and monitoring.

#### GET /logs

Retrieve information about available log files.

**Authentication:** Required

**Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `job_id` | integer | No | - | Filter logs by job ID |
| `limit` | integer | No | 50 | Maximum number of logs |

**Example Request:**

```bash
curl -H "Authorization: Bearer YOUR_KEY" \
     "http://localhost:8000/api/v1/logs?job_id=123"
```

**Example Response:**

```json
{
    "success": true,
    "data": {
        "logs": [
            {
                "filename": "arm_rip_20240115.log",
                "size": 12345,
                "modified": "2024-01-15T10:30:00"
            }
        ],
        "count": 1
    }
}
```

---

#### GET /logs/{filename}

Retrieve the contents of a specific log file.

**Authentication:** Required

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `filename` | path | The filename of the log |

**Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `lines` | integer | No | 100 | Maximum lines to return |
| `offset` | integer | No | 0 | Start from this line |

**Example Request:**

```bash
curl -H "Authorization: Bearer YOUR_KEY" \
     "http://localhost:8000/api/v1/logs/arm_rip_20240115.log?lines=50"
```

---

#### GET /logs/job/{job_id}

Retrieve the log file for a specific job.

**Authentication:** Required

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `job_id` | integer | The unique identifier of the job |

**Example Request:**

```bash
curl -H "Authorization: Bearer YOUR_KEY" \
     "http://localhost:8000/api/v1/logs/job/123"
```

---

### History

History endpoints provide access to completed/failed jobs.

#### GET /history

Retrieve completed jobs with pagination.

**Authentication:** Required

**Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `page` | integer | No | 1 | Page number |
| `per_page` | integer | No | 20 | Items per page |
| `status` | string | No | - | Filter by status (success, fail) |
| `disctype` | string | No | - | Filter by disc type |
| `video_type` | string | No | - | Filter by video type |
| `search` | string | No | - | Search in title |

**Example Request:**

```bash
curl -H "Authorization: Bearer YOUR_KEY" \
     "http://localhost:8000/api/v1/history?status=success&page=1&per_page=25"
```

**Example Response:**

```json
{
    "success": true,
    "data": {
        "history": [
            {
                "job_id": 456,
                "title": "Another Movie",
                "year": "2022",
                "status": "success",
                "disctype": "dvd",
                "video_type": "movie",
                "label": "ANOTHER_MOVIE",
                "start_time": "2024-01-10T14:00:00",
                "stop_time": "2024-01-10T14:30:00",
                "job_length": "00:30:00"
            }
        ],
        "pagination": {...}
    }
}
```

---

#### GET /history/statistics

Retrieve aggregated statistics for completed jobs.

**Authentication:** Required

**Example Request:**

```bash
curl -H "Authorization: Bearer YOUR_KEY" \
     "http://localhost:8000/api/v1/history/statistics"
```

**Example Response:**

```json
{
    "success": true,
    "data": {
        "total": 495,
        "success": 450,
        "failed": 45,
        "success_rate": 90.91,
        "by_disctype": {
            "bluray": 200,
            "dvd": 250,
            "music": 40,
            "data": 5
        },
        "by_video_type": {
            "movie": 400,
            "series": 50
        }
    }
}
```

---

## Data Models

### Job Object

| Field | Type | Description |
|-------|------|-------------|
| `job_id` | integer | Unique identifier |
| `arm_version` | string | ARM version when job was created |
| `crc_id` | string | Disc CRC identifier |
| `logfile` | string | Name of the log file |
| `start_time` | datetime | Job start time (ISO 8601) |
| `stop_time` | datetime | Job stop time (ISO 8601) |
| `job_length` | string | Total job duration (HH:MM:SS) |
| `status` | string | Job status code |
| `status_display` | string | Human-readable status name |
| `stage` | string | Current processing stage |
| `no_of_titles` | integer | Number of titles on disc |
| `title` | string | Disc title |
| `year` | string | Release year |
| `video_type` | string | Type (movie, series, music) |
| `imdb_id` | string | IMDB identifier |
| `poster_url` | string | Poster image URL |
| `disctype` | string | Disc type (bluray, dvd, music, data) |
| `label` | string | Disc label |
| `path` | string | Output path |
| `progress` | float | Current progress percentage |
| `progress_round` | integer | Rounded progress |
| `eta` | string | Estimated time remaining |
| `finished` | boolean | Whether job is finished |
| `ripping` | boolean | Whether job is actively ripping |

### Track Object

| Field | Type | Description |
|-------|------|-------------|
| `track_id` | integer | Unique identifier |
| `job_id` | integer | Parent job ID |
| `track_number` | string | Track number on disc |
| `length` | integer | Track length in seconds |
| `aspect_ratio` | string | Video aspect ratio |
| `fps` | float | Frames per second |
| `main_feature` | boolean | Whether this is the main feature |
| `basename` | string | Base filename |
| `filename` | string | Output filename |
| `ripped` | boolean | Whether track has been ripped |
| `status` | string | Processing status |
| `source` | string | Source disc type |

### Drive Object

| Field | Type | Description |
|-------|------|-------------|
| `drive_id` | integer | Unique identifier |
| `name` | string | User-defined name |
| `mount` | string | Device mount path |
| `drive_type` | string | Supported disc types |
| `drive_mode` | string | Operation mode (auto, manual) |
| `tray_status` | string | Current tray status |
| `job_id_current` | integer | Current job ID (if any) |
| `processing` | boolean | Whether drive is busy |

---

## Error Codes Reference

### Common Error Messages

| Message | Cause |
|---------|-------|
| "Authentication required" | No valid session or API key provided |
| "Admin privileges required" | Endpoint requires admin access |
| "Job with ID {id} not found" | Specified job doesn't exist |
| "Track with ID {id} not found" | Specified track doesn't exist |
| "Drive with ID {id} not found" | Specified drive doesn't exist |
| "Request body must be JSON" | Invalid content type for POST/PATCH |
| "Cannot abandon a finished job" | Job is already complete |

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2024-01 | Initial API release |

---

## Integration Examples

### Python Example - List Active Jobs

```python
import requests

API_BASE = "http://your-arm-server:8000/api/v1"
API_KEY = "your_api_key"

headers = {"Authorization": f"Bearer {API_KEY}"}

# Get active jobs
response = requests.get(f"{API_BASE}/jobs/active", headers=headers)
if response.status_code == 200:
    data = response.json()
    for job in data["data"]["jobs"]:
        print(f"{job['title']}: {job['progress']}% complete")
```

### JavaScript Example - Check System Status

```javascript
const API_BASE = 'http://your-arm-server:8000/api/v1';

async function getSystemStatus() {
    const response = await fetch(`${API_BASE}/system/status`);
    const data = await response.json();
    
    if (data.success) {
        console.log(`CPU: ${data.data.cpu_percent}%`);
        console.log(`Memory: ${data.data.memory_percent}%`);
        console.log(`Disk: ${data.data.disk_usage.percent}%`);
        console.log(`Active Jobs: ${data.data.active_jobs}`);
    }
}
```

### cURL Example - Create Notification Log Script

```bash
#!/bin/bash
# Get unread notifications every minute
API_BASE="http://your-arm-server:8000/api/v1"
API_KEY="your_api_key"

while true; do
    response=$(curl -s -H "Authorization: Bearer $API_KEY" \
        "$API_BASE}/notifications/unread")
    
    count=$(echo $response | jq -r '.data | length')
    if [ "$count" -gt 0 ]; then
        echo "You have $count unread notifications"
        echo $response | jq '.data[] | .title + ": " + .message'
    fi
    
    sleep 60
done
```

---

## Support

- **Documentation:** [ARM Wiki](https://github.com/automatic-ripping-machine/automatic-ripping-machine/wiki)
- **Issues:** [GitHub Issues](https://github.com/automatic-ripping-machine/automatic-ripping-machine/issues)
- **Discord:** [ARM Discord Server](https://discord.gg/FUSrn8jUcR)
