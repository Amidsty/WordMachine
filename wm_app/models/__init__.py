"""SQLAlchemy metadata for explicit Alembic migrations; never create_all at startup.

Legacy game storage remains intact until the dedicated game-data migration.
"""

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Computed,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.mysql import DATETIME, DOUBLE, LONGTEXT, VARCHAR
from sqlalchemy.orm import DeclarativeBase

from . import weighted_v2


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = 'user'
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(255), nullable=False)
    pwhash = Column(String(255))  # Internal legacy column name; never an API credential.
    introduction = Column(String(255))
    rating = Column(Integer)
    type = Column(String(255), server_default='normal')
    admin_level = Column(Integer, nullable=False, server_default='0')
    admin_version = Column(Integer, nullable=False, server_default='0')
    deleted = Column(Boolean)
    gamehistory = Column(Text)
    ratinghistory = Column(Text)
    rating_event_id = Column(
        BigInteger,
        ForeignKey(
            'rating_event.id', name='fk_user_rating_event', ondelete='RESTRICT', use_alter=True
        ),
    )
    rating_ledger_id = Column(
        BigInteger,
        ForeignKey(
            'game_rating.id', name='fk_user_rating_ledger', ondelete='RESTRICT', use_alter=True
        ),
    )
    __table_args__ = (
        CheckConstraint('admin_level BETWEEN 0 AND 5', name='ck_user_admin_level'),
        CheckConstraint('admin_version BETWEEN 0 AND 2147483647', name='ck_user_admin_version'),
        CheckConstraint(
            "type IS NOT NULL AND ((admin_level = 0 AND type = 'normal') OR (admin_level > 0 AND type = 'root'))",
            name='ck_user_admin_type',
        ),
        Index('uq_user_username', 'username', unique=True),
        Index('ix_user_rating_ledger', 'rating_ledger_id'),
        Index('ix_user_rating_event', 'rating_event_id'),
        Index('ix_user_deleted_rating_id', 'deleted', rating.desc(), 'id'),
        {'mysql_engine': 'InnoDB'},
    )


class AdminAudit(Base):
    __tablename__ = 'admin_audit'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    actor_id = Column(
        Integer, ForeignKey('user.id', name='fk_admin_audit_actor', ondelete='RESTRICT')
    )
    actor_level = Column(Integer)
    target_id = Column(
        Integer,
        ForeignKey('user.id', name='fk_admin_audit_target', ondelete='RESTRICT'),
        nullable=False,
    )
    action = Column(String(32), nullable=False)
    before_data = Column(JSON, nullable=False)
    after_data = Column(JSON, nullable=False)
    reason = Column(String(500), nullable=False)
    source = Column(String(16), nullable=False)
    recorded_at = Column(DATETIME(fsp=6), nullable=False)
    __table_args__ = (
        Index('ix_admin_audit_target_id', 'target_id', 'id'),
        {'mysql_engine': 'InnoDB'},
    )


class DictionaryPromotion(Base):
    __tablename__ = 'dictionary_promotion'
    request_id = Column(String(36, collation='ascii_bin'), primary_key=True)
    dict_id = Column(
        Integer,
        ForeignKey('dict.id', name='fk_promotion_dict', ondelete='RESTRICT'),
        nullable=False,
    )
    applicant_id = Column(
        Integer,
        ForeignKey('user.id', name='fk_promotion_applicant', ondelete='RESTRICT'),
        nullable=False,
    )
    submit_hash = Column(String(64), nullable=False)
    reason = Column(String(500), nullable=False)
    submitted_at = Column(DATETIME(fsp=6), nullable=False)
    state = Column(Integer, nullable=False, server_default='0')
    pending_dict_id = Column(
        Integer, Computed('CASE WHEN state = 0 THEN dict_id ELSE NULL END', persisted=True)
    )
    reviewer_id = Column(
        Integer, ForeignKey('user.id', name='fk_promotion_reviewer', ondelete='RESTRICT')
    )
    reviewer_level = Column(Integer)
    review_reason = Column(String(500))
    reviewed_at = Column(DATETIME(fsp=6))
    review_hash = Column(String(64))
    reviewed_fingerprint = Column(String(64))
    rated_min = Column(Integer)
    rated_max = Column(Integer)
    result_version = Column(Integer)
    __table_args__ = (
        UniqueConstraint('pending_dict_id', name='uq_promotion_pending'),
        UniqueConstraint('dict_id', 'result_version', name='uq_promotion_version'),
        CheckConstraint('state IN (0,1,2)', name='ck_promotion_state'),
        CheckConstraint('CHAR_LENGTH(reason) BETWEEN 1 AND 500', name='ck_promotion_reason'),
        CheckConstraint(
            '(state = 0 AND reviewer_id IS NULL AND reviewer_level IS NULL AND review_reason IS NULL AND reviewed_at IS NULL AND review_hash IS NULL AND reviewed_fingerprint IS NULL AND rated_min IS NULL AND rated_max IS NULL AND result_version IS NULL) OR (state IN (1,2) AND reviewer_id IS NOT NULL AND reviewer_level IS NOT NULL AND reviewer_level IN (4,5) AND review_reason IS NOT NULL AND CHAR_LENGTH(review_reason) BETWEEN 1 AND 500 AND reviewed_at IS NOT NULL AND review_hash IS NOT NULL AND ((state = 1 AND reviewed_fingerprint IS NOT NULL AND rated_min IS NOT NULL AND rated_max IS NOT NULL AND rated_min <= rated_max AND result_version IS NOT NULL AND result_version > 0) OR (state = 2 AND reviewed_fingerprint IS NULL AND rated_min IS NULL AND rated_max IS NULL AND result_version IS NULL)))',
            name='ck_promotion_decision',
        ),
        Index('ix_promotion_applicant', 'applicant_id', 'submitted_at', 'request_id'),
        Index('ix_promotion_state', 'state', 'submitted_at', 'request_id'),
        {'mysql_engine': 'InnoDB'},
    )


class Dictionary(Base):
    __tablename__ = 'dict'
    id = Column(Integer, primary_key=True, autoincrement=True)
    dictname = Column(String(255))
    difficulty = Column(Integer, nullable=False, server_default='1500')
    multiplier = Column(Numeric(5, 2), nullable=False, server_default='1.00')
    rated_min = Column(Integer, nullable=False, server_default=text('-2147483648'))
    rated_max = Column(Integer, nullable=False, server_default=text('2147483647'))
    config_version = Column(Integer, nullable=False, server_default='0')
    deleted = Column(Boolean)
    ownerid = Column(
        Integer, ForeignKey('user.id', name='fk_dict_owner', ondelete='RESTRICT'), nullable=True
    )
    __table_args__ = (
        CheckConstraint('multiplier BETWEEN 0.10 AND 5.00', name='ck_dict_multiplier'),
        CheckConstraint('difficulty BETWEEN 0 AND 4000', name='ck_dict_difficulty'),
        CheckConstraint('config_version >= 0', name='ck_dict_config_version'),
        CheckConstraint('rated_min <= rated_max', name='ck_dict_rated_bounds'),
        Index('ix_dict_ownerid', 'ownerid'),
        {'mysql_engine': 'InnoDB'},
    )


class DictionaryAudit(Base):
    __tablename__ = 'dictionary_audit'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    dict_id = Column(
        Integer,
        ForeignKey('dict.id', name='fk_dict_audit_dict', ondelete='RESTRICT'),
        nullable=False,
    )
    actor_id = Column(
        Integer,
        ForeignKey('user.id', name='fk_dict_audit_actor', ondelete='RESTRICT'),
        nullable=False,
    )
    actor_level = Column(Integer, nullable=False)
    multiplier_before = Column(Numeric(5, 2))
    multiplier_after = Column(Numeric(5, 2), nullable=False)
    config_version = Column(Integer, nullable=False)
    reason = Column(String(500), nullable=False)
    recorded_at = Column(DATETIME(fsp=6), nullable=False)
    __table_args__ = (Index('ix_dict_audit_dict_id', 'dict_id', 'id'), {'mysql_engine': 'InnoDB'})


class DictionaryRatedAudit(Base):
    __tablename__ = 'dictionary_rated_audit'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    dict_id = Column(
        Integer,
        ForeignKey('dict.id', name='fk_rated_bounds_dict', ondelete='RESTRICT'),
        nullable=False,
    )
    actor_id = Column(
        Integer,
        ForeignKey('user.id', name='fk_rated_bounds_actor', ondelete='RESTRICT'),
        nullable=False,
    )
    actor_level = Column(Integer, nullable=False)
    min_before = Column(Integer, nullable=False)
    max_before = Column(Integer, nullable=False)
    min_after = Column(Integer, nullable=False)
    max_after = Column(Integer, nullable=False)
    config_version = Column(Integer, nullable=False)
    reason = Column(String(500), nullable=False)
    recorded_at = Column(DATETIME(fsp=6), nullable=False)
    __table_args__ = (
        CheckConstraint('actor_level BETWEEN 3 AND 5', name='ck_rated_bounds_actor'),
        CheckConstraint('min_before <= max_before', name='ck_rated_bounds_before'),
        CheckConstraint('min_after <= max_after', name='ck_rated_bounds_after'),
        CheckConstraint('config_version > 0', name='ck_rated_bounds_version'),
        CheckConstraint('CHAR_LENGTH(reason) BETWEEN 1 AND 500', name='ck_rated_bounds_reason'),
        Index('ix_rated_bounds_dict_id', 'dict_id', 'id'),
        {'mysql_engine': 'InnoDB'},
    )


class Word(Base):
    __tablename__ = 'word'
    id = Column(Integer, primary_key=True, autoincrement=True)
    dictid = Column(Integer)
    english = Column(String(255))
    chinese = Column(String(255))
    deleted = Column(Boolean)
    __table_args__ = (
        Index('ix_word_dict_deleted_id', 'dictid', 'deleted', 'id'),
        {'mysql_engine': 'InnoDB'},
    )


class Game(Base):
    __tablename__ = 'game'
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(VARCHAR(100, charset='utf8mb4', collation='utf8mb4_bin'))
    ownerid = Column(Integer)
    dictid = Column(Integer)
    users = Column(Text)
    wordlist = Column(Text)
    result = Column(Text)
    perf = Column(Text)
    ratingdelta = Column(Text)
    status = Column(Integer)
    version = Column(Integer, nullable=False, server_default=text('0'))
    question_mode = Column(Integer, nullable=False, server_default=text('0'))
    dictname_snapshot = Column(VARCHAR(255, charset='utf8mb4', collation='utf8mb4_bin'))
    perf_mode = Column(Integer, nullable=False, server_default='0')
    multiplier_snapshot = Column(Numeric(5, 2))
    participant_mode = Column(Integer, nullable=False, server_default=text('0'))
    participant_count = Column(Integer)
    answer_mode = Column(Integer, nullable=False, server_default=text('0'))
    answer_count = Column(Integer)
    rated = Column(Integer, nullable=False, server_default=text('1'))
    settlement_mode = Column(Integer, nullable=False, server_default=text('0'))
    rating_model = Column(Integer, nullable=False, server_default='0')
    difficulty_snapshot = Column(Integer)
    rating_parameters = Column(JSON)
    __table_args__ = (
        CheckConstraint(
            '(perf_mode = 0 AND multiplier_snapshot IS NULL) OR (perf_mode = 1 AND multiplier_snapshot IS NOT NULL AND multiplier_snapshot BETWEEN 0.10 AND 5.00 AND question_mode = 1 AND answer_mode = 1)',
            name='ck_game_multiplier',
        ),
        CheckConstraint('version >= 0', name='ck_game_version'),
        CheckConstraint(weighted_v2.MODEL_CHECK, name='ck_game_rating_model_v2'),
        CheckConstraint(
            'name IS NULL OR CHAR_LENGTH(TRIM(name)) BETWEEN 1 AND 100', name='ck_game_name'
        ),
        CheckConstraint('question_mode IN (0, 1)', name='ck_game_question_mode'),
        CheckConstraint(
            '(participant_mode = 0 AND participant_count IS NULL) OR '
            '(participant_mode = 1 AND participant_count IS NOT NULL AND participant_count > 0)',
            name='ck_game_participants',
        ),
        CheckConstraint(
            '(answer_mode = 0 AND answer_count IS NULL) OR '
            '(answer_mode = 1 AND answer_count IS NOT NULL AND answer_count >= 0 '
            'AND question_mode = 1 AND participant_mode = 1)',
            name='ck_game_answers',
        ),
        CheckConstraint('settlement_mode IN (0, 1)', name='ck_game_settlement_mode'),
        CheckConstraint('rated IN (0, 1)', name='ck_game_rated'),
        Index('ix_game_participant_status', 'participant_mode', 'status', 'id'),
        {'mysql_engine': 'InnoDB'},
    )


class GameParticipant(Base):
    __tablename__ = 'game_participant'
    game_id = Column(
        Integer,
        ForeignKey('game.id', name='fk_participant_game', ondelete='RESTRICT'),
        primary_key=True,
    )
    user_id = Column(
        Integer,
        ForeignKey('user.id', name='fk_participant_user', ondelete='RESTRICT'),
        primary_key=True,
    )
    position = Column(Integer, nullable=False)
    joined_at = Column(DATETIME(fsp=6))
    recorded_at = Column(DATETIME(fsp=6), nullable=False)
    __table_args__ = (
        UniqueConstraint('game_id', 'position', name='uq_participant_position'),
        CheckConstraint('position >= 0', name='ck_participant_position'),
        CheckConstraint('user_id > 0', name='ck_participant_user_id'),
        Index('ix_participant_user_game', 'user_id', 'game_id'),
        {'mysql_engine': 'InnoDB'},
    )


class GameQuestion(Base):
    __tablename__ = 'game_question'
    game_id = Column(
        Integer,
        ForeignKey('game.id', name='fk_question_game', ondelete='RESTRICT'),
        primary_key=True,
    )
    position = Column(Integer, primary_key=True)
    word_id = Column(Integer, nullable=False)  # Provenance only, deliberately no source-word FK.
    english = Column(String(255), nullable=False)
    chinese = Column(String(255), nullable=False)
    __table_args__ = (
        UniqueConstraint('game_id', 'word_id', name='uq_question_word'),
        CheckConstraint('position >= 0', name='ck_question_position'),
        CheckConstraint('word_id > 0', name='ck_question_word_id'),
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_bin'},
    )


class GameAnswer(Base):
    __tablename__ = 'game_answer'
    game_id = Column(Integer, primary_key=True)
    position = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    answer = Column(Text, nullable=False)
    correct = Column(Boolean, nullable=False)
    usercombo = Column(Integer, nullable=False)
    globalcombo = Column(Integer, nullable=False)
    perf_delta = Column(DOUBLE(asdecimal=False), nullable=False)
    raw_perf_delta = Column(DOUBLE(asdecimal=False))
    perf = Column(DOUBLE(asdecimal=False), nullable=False)
    rating_version = Column(String(32, collation='ascii_bin'), nullable=False)
    answered_at = Column(DATETIME(fsp=6))
    recorded_at = Column(DATETIME(fsp=6), nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ['game_id', 'position'],
            ['game_question.game_id', 'game_question.position'],
            name='fk_answer_question',
            ondelete='RESTRICT',
        ),
        ForeignKeyConstraint(
            ['game_id', 'user_id'],
            ['game_participant.game_id', 'game_participant.user_id'],
            name='fk_answer_participant',
            ondelete='RESTRICT',
        ),
        UniqueConstraint('game_id', 'position', 'user_id', name='uq_answer_weighted_identity'),
        CheckConstraint('position >= 0', name='ck_answer_position'),
        CheckConstraint('correct IN (0, 1)', name='ck_answer_correct'),
        CheckConstraint('usercombo >= 0 AND globalcombo >= 0', name='ck_answer_combos'),
        Index('ix_answer_participant', 'game_id', 'user_id', 'position'),
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_bin'},
    )


class GameSettlement(Base):
    __tablename__ = 'game_settlement'
    game_id = Column(
        Integer,
        ForeignKey('game.id', name='fk_settlement_game', ondelete='RESTRICT'),
        primary_key=True,
    )
    rated_count = Column(Integer, nullable=False)
    rating_version = Column(String(32, collation='ascii_bin'), nullable=False)
    settled_at = Column(DATETIME(fsp=6))
    recorded_at = Column(DATETIME(fsp=6), nullable=False)
    __table_args__ = (
        CheckConstraint('rated_count >= 0', name='ck_settlement_count'),
        CheckConstraint(
            weighted_v2.SETTLEMENT_CHECK,
            name='ck_settlement_rating_policy_v2',
        ),
        {'mysql_engine': 'InnoDB'},
    )


class GameRating(Base):
    __tablename__ = 'game_rating'
    rule_version = Column(
        String(32, collation='ascii_bin'), nullable=False, server_default='legacy-v1'
    )
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    game_id = Column(
        Integer,
        ForeignKey('game_settlement.game_id', name='fk_rating_settlement', ondelete='RESTRICT'),
        nullable=False,
    )
    user_id = Column(
        Integer, ForeignKey('user.id', name='fk_rating_user', ondelete='RESTRICT'), nullable=False
    )
    perf = Column(DOUBLE(asdecimal=False), nullable=False)
    rating_before = Column(Integer, nullable=False)
    delta = Column(BigInteger, nullable=False)
    rating_after = Column(Integer, nullable=False)
    __table_args__ = (
        UniqueConstraint('game_id', 'user_id', name='uq_rating_game_user'),
        UniqueConstraint('id', 'game_id', 'user_id', name='uq_rating_weighted_identity'),
        CheckConstraint(weighted_v2.RULE_CHECK, name='ck_rating_rule_v2'),
        CheckConstraint(
            'rating_after = CAST(rating_before AS DECIMAL(20, 0)) + delta',
            name='ck_rating_arithmetic',
        ),
        Index('ix_rating_user_id', 'user_id', 'id'),
        {'mysql_engine': 'InnoDB'},
    )


class RatingEvent(Base):
    __tablename__ = 'rating_event'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer, ForeignKey('user.id', name='fk_event_user', ondelete='RESTRICT'), nullable=False
    )
    sequence = Column(Integer, nullable=False)
    previous_id = Column(BigInteger)
    legacy_rating_id = Column(
        BigInteger, ForeignKey('game_rating.id', name='fk_event_legacy_rating', ondelete='RESTRICT')
    )
    game_rating_id = Column(
        BigInteger,
        ForeignKey('game_rating.id', name='fk_event_game_rating', ondelete='RESTRICT'),
    )
    manual_rating_id = Column(BigInteger)
    kind = Column(String(16, collation='ascii_bin'), nullable=False)
    rule_version = Column(String(32, collation='ascii_bin'), nullable=False)
    rating_before = Column(Integer, nullable=False)
    delta = Column(BigInteger, nullable=False)
    rating_after = Column(Integer, nullable=False)
    recorded_at = Column(DATETIME(fsp=6), nullable=False)
    __table_args__ = (
        UniqueConstraint('user_id', 'id', name='uq_event_user_id'),
        UniqueConstraint('user_id', 'sequence', name='uq_event_user_sequence'),
        UniqueConstraint('user_id', 'previous_id', name='uq_event_user_previous'),
        UniqueConstraint('game_rating_id', name='uq_event_game_rating'),
        UniqueConstraint('manual_rating_id', name='uq_event_manual_rating'),
        ForeignKeyConstraint(
            ['user_id', 'manual_rating_id'],
            ['manual_rating.user_id', 'manual_rating.id'],
            name='fk_event_manual_rating',
            ondelete='RESTRICT',
        ),
        ForeignKeyConstraint(
            ['user_id', 'previous_id'],
            ['rating_event.user_id', 'rating_event.id'],
            name='fk_event_previous_user',
            ondelete='RESTRICT',
        ),
        CheckConstraint('sequence >= 1', name='ck_event_sequence'),
        CheckConstraint(
            weighted_v2.EVENT_CHECK,
            name='ck_event_source_v2',
        ),
        CheckConstraint(
            '(sequence = 1 AND previous_id IS NULL) OR (sequence > 1 AND previous_id IS NOT NULL AND legacy_rating_id IS NULL)',
            name='ck_event_origin',
        ),
        CheckConstraint(
            'rating_after = CAST(rating_before AS DECIMAL(20, 0)) + delta',
            name='ck_event_arithmetic',
        ),
        {'mysql_engine': 'InnoDB'},
    )


class RatingAdjustmentRequest(Base):
    __tablename__ = 'rating_adjustment_request'
    # No actor FK: reservations must not acquire out-of-order user locks.
    actor_id = Column(Integer, primary_key=True)
    request_id = Column(String(36, collation='ascii_bin'), primary_key=True)
    payload_hash = Column(String(64, collation='ascii_bin'), nullable=False)
    response = Column(Text().with_variant(LONGTEXT, 'mysql'))
    created_at = Column(DATETIME(fsp=6), nullable=False)
    __table_args__ = ({'mysql_engine': 'InnoDB'},)


class ManualRating(Base):
    __tablename__ = 'manual_rating'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer, ForeignKey('user.id', name='fk_manual_user', ondelete='RESTRICT'), nullable=False
    )
    actor_id = Column(
        Integer, ForeignKey('user.id', name='fk_manual_actor', ondelete='RESTRICT'), nullable=False
    )
    actor_level = Column(Integer, nullable=False)
    request_id = Column(String(36, collation='ascii_bin'), nullable=False)
    last_game_rating_id = Column(
        BigInteger, ForeignKey('game_rating.id', name='fk_manual_last_game', ondelete='RESTRICT')
    )
    rating_before = Column(Integer, nullable=False)
    delta = Column(BigInteger, nullable=False)
    rating_after = Column(Integer, nullable=False)
    reason = Column(String(500), nullable=False)
    recorded_at = Column(DATETIME(fsp=6), nullable=False)
    __table_args__ = (
        UniqueConstraint('actor_id', 'request_id', name='uq_manual_request'),
        UniqueConstraint('user_id', 'id', name='uq_manual_user_id'),
        ForeignKeyConstraint(
            ['actor_id', 'request_id'],
            ['rating_adjustment_request.actor_id', 'rating_adjustment_request.request_id'],
            name='fk_manual_request',
            ondelete='RESTRICT',
        ),
        CheckConstraint('actor_level IN (4, 5)', name='ck_manual_actor_level'),
        CheckConstraint(
            'rating_after = CAST(rating_before AS DECIMAL(20, 0)) + delta AND delta <> 0',
            name='ck_manual_arithmetic',
        ),
        CheckConstraint('CHAR_LENGTH(TRIM(reason)) BETWEEN 1 AND 500', name='ck_manual_reason'),
        {'mysql_engine': 'InnoDB'},
    )


class GameRequest(Base):
    __tablename__ = 'game_request'
    # Intentionally no actor FK: avoid taking user locks before game locks.
    actor_id = Column(Integer, primary_key=True)
    request_id = Column(String(36, collation='ascii_bin'), primary_key=True)
    action = Column(String(16, collation='ascii_bin'), nullable=False)
    payload_hash = Column(String(64, collation='ascii_bin'), nullable=False)
    game_id = Column(Integer, ForeignKey('game.id', name='fk_request_game', ondelete='RESTRICT'))
    response = Column(Text().with_variant(LONGTEXT, 'mysql'))
    created_at = Column(DateTime, nullable=False)
    __table_args__ = (Index('ix_request_game', 'game_id'), {'mysql_engine': 'InnoDB'})


class AuthSession(Base):
    __tablename__ = 'auth_session'
    token_hash = Column(String(64, collation='ascii_bin'), primary_key=True)
    user_id = Column(
        Integer, ForeignKey('user.id', name='fk_session_user', ondelete='CASCADE'), nullable=False
    )
    csrf_token = Column(String(64, collation='ascii_bin'), nullable=False)
    created_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    __table_args__ = (
        Index('ix_session_user', 'user_id'),
        Index('ix_session_expiry', 'expires_at'),
        {'mysql_engine': 'InnoDB'},
    )


class AuthRateLimit(Base):
    __tablename__ = 'auth_rate_limit'
    key_hash = Column(String(64, collation='ascii_bin'), primary_key=True)
    window_started = Column(DateTime, nullable=False)
    attempts = Column(Integer, nullable=False)
    __table_args__ = (Index('ix_rate_window', 'window_started'), {'mysql_engine': 'InnoDB'})


weighted_v2.tables(Base.metadata)
