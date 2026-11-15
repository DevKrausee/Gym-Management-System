"""Start Gym Management System."""

import flet as ft

from krause_gym.app import GymApp


def main(page: ft.Page) -> None:
    GymApp(page)


if __name__ == "__main__":
    if hasattr(ft, "run"):
        ft.run(main)
    else:
        ft.app(target=main)
