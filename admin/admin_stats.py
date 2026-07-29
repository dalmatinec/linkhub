from aiogram import Router, F, types

from database import is_admin, count_users, count_push, count_admins, get_launch_date, count_broadcasts
from texts import get_text

router = Router()


@router.callback_query(F.data == "admin_stats")
async def show_stats(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(get_text("admin.not_admin"), show_alert=True)
        return

    text = get_text(
        "admin.stats.template",
        users=count_users(),
        push_on=count_push(True),
        push_off=count_push(False),
        admins=count_admins(),
        launch_date=get_launch_date(),
        broadcasts=count_broadcasts(),
    )
    await callback.message.answer(text)
    await callback.answer()
