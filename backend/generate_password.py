from getpass import getpass

from werkzeug.security import generate_password_hash

password = getpass("Choose a password: ")
confirm = getpass("Confirm password: ")

if password != confirm:
    raise SystemExit("Passwords did not match.")

print("\nPaste this into backend/.env as AUTH_PASSWORD_HASH:\n")
print(generate_password_hash(password))
