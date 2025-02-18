CREATE TABLE works(
    upTime TEXT DEFAULT "",
    workNumber TEXT,
    title TEXT,
    kind TEXT,
    state TEXT,
    downloadDate TEXT,
    downloadPriority TEXT DEFAULT 0,
    UNIQUE (workNumber)
);

CREATE TABLE STREAM(
    userId TEXT,
    time TEXT,
    title TEXT
);

CREATE TABLE upload(
    userId TEXT not NULL,
    workNumber TEXT,
    UNIQUE (userId,workNumber)
);

CREATE TABLE user(
    userId TEXT UNIQUE,
    addTime TEXT,
    recodeStream TEXT DEFAULT 'FALSE'
);
