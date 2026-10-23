-- Disposable integration-test schema only. Never run against a live database.
CREATE TABLE user (
    id INT PRIMARY KEY AUTO_INCREMENT,
    username VARCHAR(255), pwhash VARCHAR(255), introduction VARCHAR(255),
    rating INT, type VARCHAR(255), deleted BOOLEAN,
    gamehistory TEXT, ratinghistory TEXT
) ENGINE=InnoDB;
CREATE TABLE dict (
    id INT PRIMARY KEY AUTO_INCREMENT, dictname VARCHAR(255), deleted BOOLEAN
) ENGINE=InnoDB;
CREATE TABLE word (
    id INT PRIMARY KEY AUTO_INCREMENT, dictid INT, english VARCHAR(255), chinese VARCHAR(255), deleted BOOLEAN
) ENGINE=InnoDB;
CREATE TABLE game (
    id INT PRIMARY KEY AUTO_INCREMENT, ownerid INT, dictid INT, users TEXT,
    wordlist TEXT, result TEXT, perf TEXT, ratingdelta TEXT, status INT
) ENGINE=InnoDB;
