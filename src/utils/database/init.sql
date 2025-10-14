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


CREATE TABLE upload(
    userId TEXT not NULL,
    workNumber TEXT,
    PRIMARY KEY (userId, workNumber)
);

CREATE TABLE user(
    userId TEXT UNIQUE,
    addTime TEXT
);
