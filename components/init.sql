CREATE TABLE videos(
    upTime TEXT,
    video_number TEXT,
    title TEXT,
    kind TEXT,
    state TEXT,
    downloadDate TEXT,
    UNIQUE (video_number)
);

CREATE TABLE STREAM(
    uploader TEXT,
    time TEXT,
    title TEXT
);

CREATE TABLE upload(
    uploader TEXT not NULL,
    video_number TEXT,
    UNIQUE (uploader,video_number)
);

CREATE TABLE user(
    userId TEXT UNIQUE,
    addTime TEXT,
    recodeStream TEXT DEFAULT 'FALSE'
);
