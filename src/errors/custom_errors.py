from errors import QIException


class NotFoundPixTransaction(QIException):
    code = "QIT002001"

    def __init__(self, pix_id) -> None:
        title = "Pix transaction not found"
        http_status = 404
        description = f"Pix transaction with id {pix_id} was not found."
        translation = f"A transação Pix com id {pix_id} não foi encontrada."
        super().__init__(title, self.code, http_status, description, translation)


class ConflictingPixId(QIException):
    code = "QIT002002"

    def __init__(self, pix_id) -> None:
        title = "Pix id already used with different content"
        http_status = 409
        description = f"Pix id {pix_id} was already analyzed with a different payload."
        translation = f"O id {pix_id} já foi analisado com um conteúdo diferente."
        super().__init__(title, self.code, http_status, description, translation)


class InvalidDateTime(QIException):
    code = "QIT002003"

    def __init__(self, field, value) -> None:
        title = "Invalid date"
        http_status = 422
        description = f"The value {value} in {field} is not a real date."
        translation = f"A data informada em {field} não existe."
        super().__init__(title, self.code, http_status, description, translation)


class InvalidIpAddress(QIException):
    code = "QIT002004"

    def __init__(self, value) -> None:
        title = "Invalid IP address"
        http_status = 422
        description = f"The value {value} is not a valid IPv4 or IPv6 address."
        translation = "O IP informado não é um endereço IPv4 ou IPv6 válido."
        super().__init__(title, self.code, http_status, description, translation)
