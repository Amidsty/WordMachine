-- Synthetic frozen 0007 records, never application bootstrap or production data.
-- Current application business APIs require 0011 and must not generate this old fixture.
UPDATE game SET question_mode=1, dictname_snapshot='snapshot', participant_mode=1,
 participant_count=2, answer_mode=1, answer_count=1, settlement_mode=1,
 users=NULL, result=NULL, status=1, version=4 WHERE id=1;
INSERT INTO game_question (game_id,position,word_id,english,chinese)
 SELECT 1, CASE id WHEN 11 THEN 0 WHEN 22 THEN 1 ELSE 2 END,id,english,chinese FROM word;
INSERT INTO game_participant (game_id,user_id,position,joined_at,recorded_at)
 VALUES (1,1,0,NULL,'2020-01-01'),(1,2,1,NULL,'2020-01-01');
INSERT INTO game_answer (game_id,position,user_id,answer,correct,usercombo,globalcombo,perf_delta,perf,rating_version,answered_at,recorded_at)
 VALUES (1,0,1,'apple',1,1,1,15,1515,'legacy-v1',NULL,'2020-01-01');
INSERT INTO game_settlement (game_id,rated_count,rating_version,settled_at,recorded_at)
 VALUES (1,1,'legacy-v1',NULL,'2020-01-01');
INSERT INTO game_rating (id,game_id,user_id,perf,rating_before,delta,rating_after)
 VALUES (1,1,1,1515,1500,5,1505);
UPDATE user SET rating=1505,rating_ledger_id=1,gamehistory='[1]' WHERE id=1;
INSERT INTO auth_session (token_hash,user_id,csrf_token,created_at,expires_at)
 VALUES (REPEAT('0',64),1,REPEAT('1',64),'2020-01-01','2099-01-01');
INSERT INTO auth_rate_limit (key_hash,window_started,attempts)
 VALUES (REPEAT('2',64),'2020-01-01',2);
