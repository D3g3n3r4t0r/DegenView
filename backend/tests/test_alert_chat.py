from app import main
from app.models import User


def _user(main_chat: str, alerts_chat: str = "") -> User:
    return User.model_construct(telegram_chat_id=main_chat, telegram_signal_chat_id=alerts_chat)


def test_alerts_go_to_alerts_chat_else_main():
    assert main._signal_chat(_user("1", "-100")) == "-100"
    assert main._signal_chat(_user("1")) == "1"


def test_shared_alerts_group_gets_one_copy():
    seen: set[str] = set()
    assert main._alert_chats(seen, _user("1", "-100")) == "-100"
    assert main._alert_chats(seen, _user("2", "-100")) == ""
    assert main._alert_chats(seen, _user("3")) == "3"


def test_chatid_command():
    assert main._is_chatid_command("/chatid", "MyBot")
    assert main._is_chatid_command("/chatid@mybot", "MyBot")
    assert not main._is_chatid_command("/chatid@otherbot", "MyBot")
    assert not main._is_chatid_command("chatid please", "MyBot")
    assert not main._is_chatid_command("", "MyBot")
