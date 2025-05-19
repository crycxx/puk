import asyncio

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ChatMemberUpdated, BotCommand, BotCommandScopeDefault, BotCommandScopeAllGroupChats
from aiogram.filters import ChatMemberUpdatedFilter, StateFilter
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
import logging
logging.basicConfig(level=logging.INFO)

from db import (
    init_db, register_user, save_target, get_target_id,
    set_user_visibility, is_user_visible,
    save_whisper, get_whisper_text
)



API_TOKEN = "8137936177:AAFlsmZXsb9mDi-i5iTK5edI6KAFvmVAXhA"
BOT_USERNAME = "NexWhisperBot"

bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

class SendAnonState(StatesGroup):
    waiting_for_text = State()


# --- Функция установки команд ---
async def set_bot_commands(bot: Bot):
    private_commands = [
        BotCommand(command="start", description="Начать работу"),
        BotCommand(command="support", description="Поддержка"),
    ]
    await bot.set_my_commands(private_commands, scope=BotCommandScopeDefault())

    group_commands = [
        BotCommand(command="whisper", description="Шёпот"),
    ]
    await bot.set_my_commands(group_commands, scope=BotCommandScopeAllGroupChats())
# --- конец функции ---


@router.message(F.text == "/start")
async def handle_start(message: Message):
    await register_user(message.from_user.id)
    await set_user_visibility(message.from_user.id, True)
    link = f"https://t.me/{BOT_USERNAME}?start=user{message.from_user.id}"

    inline_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📩 Получить сообщение", url=link)]
    ])
    reply_keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💬 Поддержка")]
        ],
        resize_keyboard=True
    )

    await message.answer(
        "👋 Добро пожаловать!\n\n"
        "Перешли это сообщение другим людям, чтобы они могли отправить тебе анонимное сообщение.",
        reply_markup=inline_keyboard
    )

@router.chat_member(ChatMemberUpdatedFilter(member_status_changed=True))
async def on_bot_added(event: ChatMemberUpdated, bot: Bot):
    if event.new_chat_member.user.id != (await bot.me()).id:
        return  # Не реагируем, если это не бот

    if event.new_chat_member.status in ("member", "administrator"):
        try:
            await bot.send_message(
                chat_id=event.chat.id,
                text=(
                    "👋 Привет! Я бот для анонимных сообщений.\n\n"
                    "💌 Участники могут получить свою ссылку в ЛС командой /start, "
                    "а затем анонимно получать сообщения от других.\n\n"
                    "Также доступна команда /whisper — отправь 'шёпот' в ответ на сообщение!"
                )
            )
        except Exception as e:
            logging.warning(f"Не удалось отправить приветствие: {e}")
 

@router.message(F.text.startswith("/start user"))
async def handle_start_user(message: Message, state: FSMContext):
    param = message.text.split(" ", 1)[-1]
    if not param.startswith("user"):
        return await message.answer("❌ Неверный формат ссылки.")

    target_id = int(param.replace("user", ""))
    sender_id = message.from_user.id

    if sender_id == target_id:
        return await message.answer("❌ Ты не можешь отправить сообщение самому себе.")
    if not await is_user_visible(target_id):
        return await message.answer("❌ Пользователь скрылся и не принимает сообщения.")

    await save_target(sender_id, target_id)
    await state.clear()

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Отправить сообщение", callback_data="send_anon")],
        [InlineKeyboardButton(text="ℹ️ Подробнее", callback_data="info_anon")]
    ])

    await message.answer(
        "📝 Это анонимная форма для отправки сообщения пользователю.\n\nЧто ты хочешь сделать?",
        reply_markup=keyboard
    )
    return None



@router.callback_query(F.data == "send_anon")
async def handle_send_anon(callback: CallbackQuery, state: FSMContext):
    await state.set_state(SendAnonState.waiting_for_text)
    await callback.message.edit_text("✉️ Напиши сообщение, которое ты хочешь отправить анонимно:")

@router.callback_query(F.data == "info_anon")
async def handle_info_anon(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        "ℹ️ Здесь ты можешь анонимно отправить сообщение пользователю.\n\n"
        "Нажми 'Отправить сообщение' и просто введи свой текст — он будет доставлен без имени отправителя."
    )


@router.message(SendAnonState.waiting_for_text, F.text)
async def process_anon_message(message: Message, state: FSMContext):
    target_id = await get_target_id(message.from_user.id)
    await state.clear()

    if not target_id:
        return await message.answer("❌ Ошибка: не удалось найти получателя.")

    try:
        await bot.send_message(
            target_id,
            f"📩 Тебе пришло <b>анонимное сообщение</b>:\n\n{message.text}",
            parse_mode="HTML"
        )
        await message.answer("✅ Твоё сообщение отправлено!")
        return None
    except Exception:
        await message.answer("❌ Не удалось доставить сообщение (возможно, пользователь заблокировал бота).")
        return None



@router.callback_query(F.data.startswith("reveal_whisper:"))
async def handle_whisper(callback: CallbackQuery):
    _, receiver_id, msg_id = callback.data.split(":")
    receiver_id = int(receiver_id)
    msg_id = int(msg_id)

    if callback.from_user.id != receiver_id:
        return await callback.answer("❌ Это сообщение не для тебя.", show_alert=True)

    # Получаем шёпот (без удаления)
    whisper_text = await get_whisper_text(msg_id, receiver_id)

    if not whisper_text:
        return await callback.answer("❗ Шёпот не найден.", show_alert=True)

    return await callback.answer(f"💬 Шёпот: {whisper_text}", show_alert=True)


@router.message(Command("whisper"))
async def send_whisper(message: Message):
    if not message.reply_to_message:
        return await message.reply("❗ Используй команду в ответ на сообщение.")

    target = message.reply_to_message.from_user
    if target.is_bot:
        return await message.reply("❗ Нельзя отправить шёпот боту.")

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await message.reply("❗ Укажи текст шёпота после команды.")

    whisper_text = parts[1]

    try:
        await message.delete()
    except TelegramBadRequest:
        pass

    # Сначала создаём сообщение без кнопки, потом получаем его ID
    sent = await bot.send_message(
        chat_id=message.chat.id,
        text=f"💬 Шёпот для @{target.username or target.full_name}"
    )

    # Теперь добавляем inline-кнопку с правильным message_id
    await bot.edit_message_reply_markup(
        chat_id=sent.chat.id,
        message_id=sent.message_id,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="Посмотреть шёпот 👁",
                callback_data=f"reveal_whisper:{target.id}:{sent.message_id}"
            )]
        ])
    )

    await save_whisper(sent.message_id, target.id, whisper_text)
    return None

@router.message(F.text == "💬 Поддержка")
async def handle_support(message: Message):
    support_users = [
        {"name": "cry", "username": "cvvcrying"},
        {"name": "Мария", "username": "support2"}
    ]

    contact_lines = [
        f"👤 <b>{user['name']}</b>: @{user['username']}" for user in support_users
    ]
    contacts_text = "\n".join(contact_lines)

    await message.answer(
        "❓ <b>Нужна помощь?</b>\n\n"
        "Свяжись с нашей поддержкой:\n\n"
        f"{contacts_text}",
        parse_mode="HTML"
    )

@dp.message(Command("support"))
async def cmd_support(message: Message):
    support_users = [
        {"name": "cry", "username": "cvvcrying"},
        {"name": "Мария", "username": "support2"},
    ]

    contact_lines = [
        f"👤 <b>{user['name']}</b>: @{user['username']}" for user in support_users
    ]
    contacts_text = "\n".join(contact_lines)

    await message.answer(
        "❓ <b>Нужна помощь?</b>\n\n"
        "Свяжитесь с нашей поддержкой:\n\n"
        f"{contacts_text}",
        parse_mode="HTML"
    )


async def main():
    await init_db()  # Инициализация базы данных
    await set_bot_commands(bot)  # Установка команд
    await dp.start_polling(bot)  # Запуск бота

if __name__ == "__main__":
    asyncio.run(main())
