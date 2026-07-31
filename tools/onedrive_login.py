"""Login unico no OneDrive: gera o refresh token que o robo vai usar.

    python -m tools.onedrive_login

Voce so roda isso uma vez (ou quando o acesso for revogado).
"""
import os
import sys

sys.path.insert(0, __file__.rsplit("tools", 1)[0])

from src import msauth  # noqa: E402


def main():
    client_id = os.environ.get("ONEDRIVE_CLIENT_ID", "").strip()
    if not client_id:
        client_id = input("Cole aqui o ID do aplicativo (cliente) do Azure: ").strip()
    if not client_id:
        print("Sem client id nao da para continuar.")
        return 1

    print("\nAbrindo o login da Microsoft...\n")
    try:
        resultado = msauth.device_code_login(client_id)
    except RuntimeError as e:
        print(f"\nFALHOU: {e}")
        return 1

    refresh = resultado.get("refresh_token")
    if not refresh:
        print("\nA Microsoft nao devolveu refresh token. Confira se o app pede "
              "o escopo 'offline_access'.")
        return 1

    print("\n" + "=" * 70)
    print("Deu certo. Cadastre estes dois secrets no GitHub:")
    print("=" * 70)
    print(f"\nONEDRIVE_CLIENT_ID:\n{client_id}")
    print(f"\nONEDRIVE_REFRESH_TOKEN:\n{refresh}")
    print("\n" + "=" * 70)
    print("Nao compartilhe o refresh token: ele da acesso de leitura ao seu OneDrive.")

    caminho = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "onedrive-token.local.txt")
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(f"ONEDRIVE_CLIENT_ID={client_id}\nONEDRIVE_REFRESH_TOKEN={refresh}\n")
    print(f"\nTambem salvei em {caminho} (o .gitignore impede que suba para o GitHub).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
