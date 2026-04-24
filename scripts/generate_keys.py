from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import os

def generate_keys():
    print("Generating RSA keys...")
    
    # Generate private key
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048
    )

    # Private key in PEM format
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption()
    )

    # Public key in PEM format
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )

    # Save to files
    with open("jwt_private.pem", "wb") as f:
        f.write(private_pem)
    
    with open("jwt_public.pem", "wb") as f:
        f.write(public_pem)

    print("\n✅ Keys generated successfully!")
    print("- jwt_private.pem")
    print("- jwt_public.pem")
    print("\nIMPORTANT: Keep these files safe and NEVER commit them to Git.")

if __name__ == "__main__":
    generate_keys()
