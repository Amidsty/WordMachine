class ApiError(Exception):
    def __init__(self, message, status=400, code='invalid_parameters', details=None):
        super().__init__(message)
        self.message, self.status, self.code = message, status, code
        self.details = details

    def payload(self):
        result = {'success': False, 'code': self.code, 'message': self.message}
        if self.details is not None:
            result['details'] = self.details
        return result


class GameError(ApiError):
    def __init__(self, message, status=409, code='invalid_game_state'):
        super().__init__(message, status, code)


def positive_int(data, name):
    value = data.get(name)
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise GameError(f'Invalid {name}', 400, 'invalid_parameters')
    try:
        number = int(value)
    except ValueError:
        raise GameError(f'Invalid {name}', 400, 'invalid_parameters') from None
    if number <= 0:
        raise GameError(f'Invalid {name}', 400, 'invalid_parameters')
    return number


def text(data, name, max_length=255):
    value = data.get(name)
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise GameError(f'Invalid {name}', 400, 'invalid_parameters')
    return value.strip()
