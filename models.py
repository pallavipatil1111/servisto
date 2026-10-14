from flask_login import UserMixin


class User(UserMixin):
    def __init__(self, id, email, password_hash, first_name, last_name, phone, address, user_type, created_at):
        self.id = id
        self.email = email
        self.password_hash = password_hash
        self.first_name = first_name
        self.last_name = last_name
        self.phone = phone
        self.address = address
        self.user_type = user_type
        self.created_at = created_at

    @classmethod
    def from_row(cls, row):
        return cls(**{key: row[key] for key in (
            'id', 'email', 'password_hash', 'first_name', 'last_name',
            'phone', 'address', 'user_type', 'created_at')})

    @property
    def is_provider(self):
        return self.user_type == 'provider'

    def get_id(self):
        return str(self.id)
