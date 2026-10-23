import { onScopeDispose, ref } from 'vue'
import { ApiError } from '../api/client'

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const messages: Record<string, string> = {
      invalid_credentials: '用户名或密码不正确，请检查后重试。',
      username_exists: '用户名已被使用，请选择其他名称。',
      unauthenticated: '登录已失效，请重新登录。',
      csrf_failed: '安全校验已过期，已尝试刷新登录状态；请确认内容后重新提交。',
      database_unavailable: '服务暂时不可用，请稍后重试。',
      forbidden: '没有执行此操作的权限。',
      game_end_forbidden: '仅房主或 Lv.2+ 管理员可手动结束；请发送结束请求联系处理。',
      invalid_end_request: '结束请求留言需为 1–500 个字符，不能含控制字符。',
      game_not_running: '对局已不在进行中，未发送新的结束请求。',
      end_request_exists: '你已为本局发送过结束请求，请刷新核对；不会重复发送。',
      invalid_game_participants: '对局参赛记录异常，请联系管理员审查。',
      invalid_game_answers: '对局答题记录异常，请联系管理员审查。',
      invalid_game_settlement: '对局结算或评分流水异常，请联系管理员审查。',
      rating_out_of_range: '评分超出支持范围，未提交本次操作，请联系管理员。',
      invalid_game_snapshot: '对局题目快照异常，请联系管理员审查。',
      invalid_dictionary_data: '词典内容异常，请先审查单词后再创建对局。',
      dictionary_too_large: '词典题目数量超出当前对局存储上限，请使用较小的词典。',
      rated_system_dictionary_required:
        'Rated 仅允许使用未删除的系统词典；个人词典请创建 Unrated。',
      rated_rating_out_of_range:
        '所有参赛者的当前 Rating 都必须在系统词典 Rated 区间内；请核对成员和最新区间。',
      invalid_rated_bounds: 'Rated 区间必须是有效整数且下界不大于上界；已保存配置异常时需审查。',
      invalid_multiplier: '倍率需为 0.10–5.00，最多两位小数；已存快照异常时需管理员审查。',
      reason_required: '修改系统词典倍率需填写原因。',
      invalid_game_name: '比赛名称需为 1–100 个字符且不能含换行或控制字符；旧名称异常时需审查。',
      unchanged_game_name: '比赛名称未变化。',
      promotion_pending: '该词典已有待审核申请，请先查看申请记录。',
      promotion_conflict: '申请已处理或词典状态已变化，请刷新申请记录核对；未自动重发。',
      stale_promotion_review: '词条、配置已变化或审查已过期，请关闭后重新审查；未自动重发。',
      stale_dictionary_version: '词典配置已变化，请关闭弹窗并刷新后重新审查；未自动重发。',
      stale_admin_version: '用户权限已变化，请关闭弹窗并刷新后重新审查。',
      stale_rating: 'Rating 或流水版本已变化，请重新审查后创建新请求；未自动重发。',
      rating_game_running: '该用户正在进行对局，结束后才能调整 Rating。',
      invalid_rating_event: '评分流水异常，请联系管理员运行 audit-legacy 审查；未自动修复。',
      rating_sequence_exhausted: '评分流水序号已耗尽，请联系管理员审查。',
      invalid_account_state: '账号状态需要审查，请刷新或联系管理员。',
      stale_game_version: '对局已变化，请关闭弹窗并刷新后重试。',
      request_id_conflict: '请求编号已用于其他操作，请刷新后重新操作。',
      empty_dictionary: '词典没有可用单词，请先添加单词。',
      legacy_data_error: '历史对局数据需要审查，请联系管理员运行 audit-legacy；未自动修复或重算。',
      not_found: '记录不存在或已删除，请刷新后确认。',
      invalid_game_rating_policy: '比赛 Rated / Unrated 记录异常，需审查；未自动改用其他模式。',
      invalid_word_range:
        '区间需满足 1 ≤ l ≤ r ≤ 当前有效单词数，且不超过 2147483647；请核对全词典序号。',
      invalid_range_confirmation: '删除确认无效，请重新预览并确认；未执行自动重发。',
      stale_word_range:
        '词表或词典已变化，或确认已过期。请先核对操作结果，再重新预览确认；不会自动删除后移的区间。',
      invalid_csv: 'CSV 校验失败，整批未导入，请检查错误行。',
      csv_too_large: 'CSV 超过服务器大小限制。',
      csv_too_many_rows: 'CSV 超过服务器行数限制。',
    }
    if (error.code === 'rate_limited') {
      return error.retryAfter
        ? `操作过于频繁，请在 ${error.retryAfter} 秒后重试。`
        : '操作过于频繁，请稍后重试。'
    }
    return messages[error.code] ?? error.message
  }
  return '网络异常，请确认操作结果后再重试；未自动重复提交。'
}

export function useFormTask() {
  const pending = ref(false)
  const error = ref('')
  const controller = new AbortController()
  onScopeDispose(() => controller.abort())
  async function run(operation: (signal: AbortSignal) => Promise<void>) {
    if (pending.value) return
    pending.value = true
    error.value = ''
    try {
      await operation(controller.signal)
    } catch (cause) {
      if (!controller.signal.aborted) error.value = errorMessage(cause)
    } finally {
      pending.value = false
    }
  }
  return { pending, error, run }
}
