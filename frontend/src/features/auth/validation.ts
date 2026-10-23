export function newPasswordError(password: string, adminLevel = 0) {
  const length = Array.from(password).length
  if (adminLevel === 5) {
    return length >= 16 &&
      length <= 128 &&
      /[a-z]/.test(password) &&
      /[A-Z]/.test(password) &&
      /[0-9]/.test(password) &&
      /[\x21-\x2f\x3a-\x40\x5b-\x60\x7b-\x7e]/.test(password)
      ? ''
      : '5 级管理员密码需为 16–128 个字符，包含大小写字母、数字和符号。'
  }
  return length >= 6 && length <= 128 ? '' : '密码需为 6–128 个字符。'
}

export function confirmationError(password: string, confirmation: string) {
  return password === confirmation ? '' : '两次输入的密码不一致。'
}
