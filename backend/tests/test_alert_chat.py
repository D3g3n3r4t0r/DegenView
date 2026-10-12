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


# Lorenzo, 12/10: "in the strategy alerts chat I also get the optimization
# finished and the new gems in the leaderboard. In this chat I only want
# trading signals when the strategies fire."
def _users(monkeypatch, *users):
    monkeypatch.setattr(main.auth, "list_users", lambda: list(users))


def test_info_goes_to_the_main_chat_not_the_alerts_chat(monkeypatch):
    me = _user("111", "-5359869020")
    _users(monkeypatch, me)
    assert main._info_chat(me) == "111"
    assert main._signal_chat(me) == "-5359869020"


def test_an_alerts_chat_never_gets_info_even_as_someones_main_chat(monkeypatch):
    lorenzo = _user("111", "-5359869020")
    other = _user("-5359869020")          # another account, main chat = the group
    _users(monkeypatch, lorenzo, other)
    assert main._info_chat(other) == ""
    same = _user("-5359869020", "-5359869020")
    _users(monkeypatch, same)
    assert main._info_chat(same) == ""


def test_info_broadcast_reaches_each_main_chat_once(monkeypatch):
    a, b = _user("111", "-100"), _user("111", "-100")
    _users(monkeypatch, a, b)
    seen: set[str] = set()
    assert main._info_chats(seen, a) == "111"
    assert main._info_chats(seen, b) == ""
