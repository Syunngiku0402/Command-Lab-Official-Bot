from enum import Enum
import enum
import math
from random import shuffle
import re
from typing import Any, Callable, Coroutine
import typing
from uuid import UUID
import uuid

from discord import Team

from .registry import Registries

from .source import CommandSource
from .util.consumer import Consumer
from lib.commands.util import Predicate, Vec3d
from lib.commands.entity import Entity, EntityType, GameMode, LivingEntity, ServerPlayerEntity
from lib.commands.number_range import FloatRnage, IntRange
from lib.commands.exceptions import SimpleCommandExceptionType, DynamicCommandExceptionType
from lib.commands.text import Text
from brigadier import StringReader
from brigadier.suggestion import SuggestionsBuilder
from lib.commands import util

SELECTOR_PREFIX = '@'
ARGUMENTS_OPENING = '['
ARGUMENTS_CLOSING = ']'
ARGUMENT_DEFINER = '='
ARGUMENT_SEPARATOR = ','
INVERT_MODIFIER = '!'
TAG_MODIFIER = '#'
NEAREST_PLAYER = 'p'
ALL_PLAYERS = 'a'
RANDOM_PLAYER = 'r'
SELF = 's'
ALL_ENTITIES = 'e'
INVALID_ENTITY_EXCEPTION = SimpleCommandExceptionType(Text.translatable("argument.entity.invalid"))
UNKNOWN_SELECTOR_EXCEPTION = DynamicCommandExceptionType(lambda option: Text.stringifiedTranslatable("argument.entity.selector.unknown", option))
NOT_ALLOWED_EXCEPTION = SimpleCommandExceptionType(Text.translatable("argument.entity.selector.not_allowed"))
MISSING_EXCEPTION = SimpleCommandExceptionType(Text.translatable("argument.entity.selector.missing"))
UNTERMINATED_EXCEPTION = SimpleCommandExceptionType(Text.translatable("argument.entity.options.unterminated"))
VALUELESS_EXCEPTION = DynamicCommandExceptionType(lambda option: Text.stringifiedTranslatable("argument.entity.options.valueless", option))


def NEAREST(pos: Vec3d, entities: list[Entity]):
    entities.sort(key=lambda e: e.squeredDistanceTo(pos))


def FURTHEST(pos: Vec3d, entities: list[Entity]):
    entities.sort(key=lambda e: e.squeredDistanceTo(pos), reverse=True)


def RANDOM(pos: Vec3d, entities: list[Entity]):
    shuffle(list)


def ARBITRARY(pos: Vec3d, entities: list[Entity]):
    pass


def DEFAULT_SUGGESTION_PROVIDER(builder: SuggestionsBuilder, consumer: Callable):
    return builder.build_async()


class EntitySelectorReader:
    reader: StringReader
    atAllowed: bool
    limit: int
    includesNonPlayers: bool
    localWorldOnly: bool
    distance: FloatRnage
    levelRange: IntRange
    x: float
    y: float
    z: float
    dx: float
    dy: float
    dz: float
    pitchRange: FloatRnage
    yawRange: FloatRnage
    predicate: Predicate[Entity]
    sorter: Callable
    senderOnly: bool
    playerName: str
    startCursor: int
    uuid: UUID
    suggestionProvider: Coroutine[Any, Any, SuggestionsBuilder]
    selectsName: bool
    excludesName: bool
    hasLimit: bool
    hasSorter: bool
    selectsGameMode: bool
    excludesGameMode: bool
    selectsTeam: bool
    excludesTeam: bool
    entityType: EntityType
    excludesEntityType: bool
    selectsScores: bool
    selectsAdvancements: bool
    usesAt: bool

    def __init__(self, reader: StringReader, atAllowed: bool):
        self.distance = FloatRnage.any()
        self.levelRange = IntRange.any()
        self.pitchRange = FloatRnage.any()
        self.yawRange = FloatRnage.any()
        self.predicate = lambda entity: True
        self.sorter = ARBITRARY
        self.suggestionProvider = DEFAULT_SUGGESTION_PROVIDER
        self.reader = reader
        self.atAllowed = atAllowed

    def read_at_variable(self):
        self.usesAt = True
        self.suggestionProvider = self.suggest_selector_rest
        if not self.reader.can_read():
            raise MISSING_EXCEPTION.create_with_context(self.reader)
        else:
            i = self.reader.get_cursor()
            c = self.reader.read()
            if c == 'p':
                self.limit = 1
                self.includesNonPlayers = False
                self.sorter = NEAREST
                self.set_entity_type(EntityType.PLAYER)
            elif c == 'a':
                self.limit = util.MAX_INT
                self.includesNonPlayers = False
                self.sorter = ARBITRARY
                self.set_entity_type(EntityType.PLAYER)
            elif c == 'r':
                self.limit = 1
                self.includesNonPlayers = False
                self.sorter = RANDOM
                self.set_entity_type(EntityType.PLAYER)
            elif c == 's':
                self.limit = 1
                self.includesNonPlayers = True
                self.senderOnly = True
            else:
                if c != 'e':
                    self.reader.set_cursor(i)
                    UNKNOWN_SELECTOR_EXCEPTION.create_with_context(self.reader, "@" + str(c))

                self.limit = util.MAX_INT
                self.includesNonPlayers = True
                self.sorter = ARBITRARY
                self.predicate = Entity.is_alive

            self.suggestionProvider = self.suggest_open
            if self.reader.can_read() and self.reader.peek() == '[':
                self.reader.skip()
                self.suggestionProvider = self.suggest_option_or_end
                self.read_arguments()

    def read_regular(self):
        if self.reader.can_read():
            self.suggestionProvider = self.suggest_normal

        i: int = self.reader.get_cursor()
        string = self.reader.read_string()

        try:
            self.uuid = UUID(string)
            self.includesNonPlayers = True
        except Exception:
            if string == "" or len(string) > 16:
                self.reader.set_cursor(i)
                raise INVALID_ENTITY_EXCEPTION.create_with_context(self.reader)

            self.includesNonPlayers = False
            self.playerName = string

        self.limit = 1

    def read_arguments(self):
        self.suggestionProvider = self.suggest_option
        self.reader.skip_whitespace()

        while self.reader.can_read() and self.reader.peek() != ']':
            self.reader.skip_whitespace()
            i = self.reader.get_cursor()
            string = self.reader.read_string()
            selectorHandler = EntitySelectorOptions.get_handler(self, string, i)
            self.reader.skip_whitespace()
            if self.reader.can_read() and self.reader.peek() == '=':
                self.reader.skip()
                self.reader.skip_whitespace()
                self.suggestionProvider = DEFAULT_SUGGESTION_PROVIDER
                selectorHandler.handle(self)
                self.reader.skip_whitespace()
                self.suggestionProvider = self.suggest_end_next
                if not self.reader.can_read():
                    continue

                if self.reader.peek() == ',':
                    self.reader.skip()
                    self.suggestionProvider = self.suggest_option
                    continue

                if self.reader.peek() != ']':
                    raise UNTERMINATED_EXCEPTION.create_with_context(self.reader)
                break

            self.reader.set_cursor(i)
            raise VALUELESS_EXCEPTION.create_with_context(self.reader, string)

        if self.reader.can_read():
            self.reader.skip()
            self.suggestionProvider = DEFAULT_SUGGESTION_PROVIDER
        else:
            raise UNTERMINATED_EXCEPTION.create_with_context(self.reader)

    async def _suggest_selector(self, builder: SuggestionsBuilder) -> None:
        builder.suggest("@p", Text.translatable("argument.entity.selector.nearestPlayer"))
        builder.suggest("@a", Text.translatable("argument.entity.selector.allPlayers"))
        builder.suggest("@r", Text.translatable("argument.entity.selector.randomPlayer"))
        builder.suggest("@s", Text.translatable("argument.entity.selector.self"))
        builder.suggest("@e", Text.translatable("argument.entity.selector.allEntities"))

    async def suggest_selector(self, builder: SuggestionsBuilder, consumer: Consumer[SuggestionsBuilder]):
        consumer.accept(builder)
        if self.atAllowed:
            self._suggest_selector(builder)

        return builder.build_async()

    async def suggest_normal(self, builder: SuggestionsBuilder, consumer: Consumer[SuggestionsBuilder]):
        suggestionsBuilder = builder.create_offset(self.startCursor)
        consumer.accept(suggestionsBuilder)
        return builder.add(suggestionsBuilder).build_async()

    async def suggest_selector_rest(self, builder: SuggestionsBuilder, consumer: Consumer[SuggestionsBuilder]):
        suggestionsBuilder = builder.create_offset(builder.get_start() - 1)
        self.suggest_selector(suggestionsBuilder)
        builder.add(suggestionsBuilder)
        return builder.build_async()

    async def suggest_open(self, builder: SuggestionsBuilder, consumer: Consumer[SuggestionsBuilder]):
        builder.suggest(str('['))
        return builder.build_async()

    async def suggest_option_or_end(self, builder: SuggestionsBuilder, consumer: Consumer[SuggestionsBuilder]):
        builder.suggest(str(']'))
        EntitySelectorOptions.suggestOptions(self, builder)
        return builder.build_async()

    async def suggest_option(self, builder: SuggestionsBuilder, consumer: Consumer[SuggestionsBuilder]):
        EntitySelectorOptions.suggestOptions(self, builder)
        return builder.build_async()

    async def suggest_end_next(self, builder: SuggestionsBuilder, consumer: Consumer[SuggestionsBuilder]):
        builder.suggest(str(','))
        builder.suggest(str(']'))
        return builder.build_async()

    async def suggestDefinerNext(self, builder: SuggestionsBuilder, consumer: Consumer[SuggestionsBuilder]):
        builder.suggest(str('='))
        return builder.build_async()

    def get_reader(self) -> StringReader:
        return self.reader

    def set_predicate(self, condition: Predicate["EntitySelectorReader"]):
        self.predicate = condition

    def read_negation_character(self) -> bool:
        self.reader.skip_whitespace()
        if self.reader.can_read() and self.reader.peek() == '!':
            self.reader.skip()
            self.reader.skip_whitespace()
            return True
        else:
            return False

class SelectorHandler():
    def handle(reader: EntitySelectorReader):
        raise NotImplementedError()

class SelectorOption:
    handler: SelectorHandler
    condition: Predicate["EntitySelectorOptions"]
    description: Text

    def __init__(self, handler: SelectorHandler, condition: Predicate["EntitySelectorOptions"], description: Text):
        self.handler = handler
        self.condition = condition
        self.description = description


    def handler(self) -> SelectorHandler:
        return self.handler


    def condition(self) -> Predicate["EntitySelectorOptions"]:
        return self.condition


UNKNOWN_OPTION_EXCEPTION = DynamicCommandExceptionType(lambda option: Text.stringifiedTranslatable("argument.entity.options.unknown", [option]))
INAPPLICABLE_OPTION_EXCEPTION = DynamicCommandExceptionType(lambda option: Text.stringifiedTranslatable("argument.entity.options.inapplicable", [option]));
NEGATIVE_DISTANCE_EXCEPTION = SimpleCommandExceptionType(Text.translatable("argument.entity.options.distance.negative"));
NEGATIVE_LEVEL_EXCEPTION = SimpleCommandExceptionType(Text.translatable("argument.entity.options.level.negative"));
TOO_SMALL_LEVEL_EXCEPTION = SimpleCommandExceptionType(Text.translatable("argument.entity.options.limit.toosmall"));
IRREVERSIBLE_SORT_EXCEPTION = DynamicCommandExceptionType(lambda option: Text.stringifiedTranslatable("argument.entity.options.sort.irreversible", [option]))
INVALID_MODE_EXCEPTION = DynamicCommandExceptionType(lambda gamemode: Text.stringifiedTranslatable("argument.entity.options.mode.invalid", [gamemode]))
INVALID_TYPE_EXCEPTION = DynamicCommandExceptionType(lambda entity: Text.stringifiedTranslatable("argument.entity.options.type.invalid", [entity]))


class EntitySelectorOptions():
    def __init__(self) -> None:
        self.options: dict[str, SelectorOption] = {}

    def put_option(self, id: str, handler: SelectorHandler, condition: Predicate[EntitySelectorReader], description: Text):
        self.options[id] = SelectorOption(handler, condition, description)

    def init(self):
        # ---------------------------------------------------------------------------------

        class NameOption(SelectorHandler):
            def handle(reader: EntitySelectorReader):
                i = reader.get_reader().get_cursor()
                bl = reader.read_negation_character()
                string = reader.get_reader().read_string()
                if reader.excludesName() and not bl:
                    reader.get_reader().set_cursor(i)
                    raise INAPPLICABLE_OPTION_EXCEPTION.create_with_context(reader.get_reader(), "name")
                else:
                    if bl:
                        reader.excludesName = True
                    else:
                        reader.selectsName = True

                    def _predicate(readerx: Entity) -> bool:
                        return readerx.get_name().get_string().equals(string) != bl

                    reader.set_predicate(_predicate)

        self.put_option(
            "name",
            NameOption(),
            lambda reader: not reader.selects_name,
            Text.translatable("argument.entity.options.name.description")
        )

        # ---------------------------------------------------------------------------------

        class DistanceOption(SelectorHandler):
            def handle(reader: EntitySelectorReader):
                i = reader.get_reader().get_cursor()
                doubleRange = FloatRnage.parse(reader.get_reader())
                if ((doubleRange.min is None or doubleRange.min < 0.0)) and (doubleRange.max is None or not ((doubleRange.max < 0.0))):
                    reader.distance = doubleRange
                    reader.set_local_world_only()
                else:
                    reader.get_reader().set_cursor(i)
                    raise NEGATIVE_DISTANCE_EXCEPTION.create_with_context(reader.get_reader())

        self.put_option(
            "distance",
            DistanceOption(),
            lambda reader: not reader.distance.is_dummy(),
            Text.translatable("argument.entity.options.distance.description")
        )

        # ---------------------------------------------------------------------------------

        class LevelOption(SelectorHandler):
            def handle(reader: EntitySelectorReader):
                i = reader.get_reader().get_cursor()
                intRange = IntRange.parse(reader.get_reader())
                if ((intRange is None or intRange.min >= 1) and (intRange.max is None or intRange.max >= 0)):
                    reader.levelRange = intRange
                    reader.includesNonPlayers = False
                else:
                    reader.get_reader().set_cursor(i)
                    raise NEGATIVE_LEVEL_EXCEPTION.create_with_context(reader.get_reader())

        self.put_option(
            "level",
            LevelOption(),
            lambda reader: not reader.levelRange.is_dummy(),
            Text.translatable("argument.entity.level.distance.description")
        )

        # ---------------------------------------------------------------------------------

        class XOption(SelectorHandler):
            def handle(reader: EntitySelectorReader):
                reader.set_local_world_only()
                reader.x = reader.get_reader().read_float()

        class YOption(SelectorHandler):
            def handle(reader: EntitySelectorReader):
                reader.set_local_world_only()
                reader.x = reader.get_reader().read_float()

        class ZOption(SelectorHandler):
            def handle(reader: EntitySelectorReader):
                reader.set_local_world_only()
                reader.x = reader.get_reader().read_float()

        self.put_option("x", XOption(), lambda reader: reader.x == None, Text.translatable("argument.entity.options.x.description"))
        self.put_option("y", YOption(), lambda reader: reader.y == None, Text.translatable("argument.entity.options.y.description"))
        self.put_option("z", ZOption(), lambda reader: reader.z == None, Text.translatable("argument.entity.options.z.description"))

        # ---------------------------------------------------------------------------------

        class DXOption(SelectorHandler):
            def handle(reader: EntitySelectorReader):
                reader.set_local_world_only()
                reader.x = reader.get_reader().read_float()

        class DYOption(SelectorHandler):
            def handle(reader: EntitySelectorReader):
                reader.set_local_world_only()
                reader.x = reader.get_reader().read_float()

        class DZOption(SelectorHandler):
            def handle(reader: EntitySelectorReader):
                reader.set_local_world_only()
                reader.x = reader.get_reader().read_float()

        self.put_option("dx", DXOption(), lambda reader: reader.x == None, Text.translatable("argument.entity.options.x.description"))
        self.put_option("dy", DYOption(), lambda reader: reader.y == None, Text.translatable("argument.entity.options.y.description"))
        self.put_option("dz", DZOption(), lambda reader: reader.z == None, Text.translatable("argument.entity.options.z.description"))

        # ---------------------------------------------------------------------------------

        class XRotationOption(SelectorHandler):
            def handle(reader: EntitySelectorReader):
                reader.pitchRange = math.degrees(FloatRnage.parse(reader.get_reader()))

        class YRotationOption(SelectorHandler):
            def handle(reader: EntitySelectorReader):
                reader.yawRange = math.degrees(FloatRnage.parse(reader.get_reader()))

        self.put_option("x_rotation", XRotationOption(), lambda reader: FloatRnage.any().test(reader.pitchRange))
        self.put_option("y_rotation", YRotationOption(), lambda reader: FloatRnage.any().test(reader.yawRange))

        # ---------------------------------------------------------------------------------

        class LimitOption(SelectorHandler):
            def handle(reader: EntitySelectorReader):
                i = reader.get_reader().get_cursor()
                j = reader.get_reader().read_int()
                if (j < 1):
                    reader.get_reader().set_cursor(i)
                    raise TOO_SMALL_LEVEL_EXCEPTION.create_with_context(reader.get_reader())
                else:
                    reader.limit = j
                    reader.hasLimit = True

        self.put_option("limit", LimitOption(), lambda reader: not reader.senderOnly and not reader.hasLimit, Text.translatable("argument.entity.options.limit.description"))

        # ---------------------------------------------------------------------------------

        class SortOption(SelectorHandler):
            def handle(reader: EntitySelectorReader):
                i = reader.get_reader().get_cursor()
                string = reader.get_reader().read_unquoted_string()

                def _provider(builder, consumer):
                    return CommandSource.suggestMatching(("nearest", "furthest", "random", "arbitrary"), builder)

                reader.suggestionProvider = _provider
                if string == "nearest":
                    reader.sorter = NEAREST
                    reader.hasSorter = True
                elif string == "furthest":
                    reader.sorter = FURTHEST
                    reader.hasSorter = True
                elif string == "random":
                    reader.sorter = RANDOM
                    reader.hasSorter = True
                elif string == "arbitrary":
                    reader.sorter = ARBITRARY
                    reader.hasSorter = True
                else:
                    reader.get_reader().set_cursor(i)
                    raise IRREVERSIBLE_SORT_EXCEPTION.create_with_context(reader.get_reader(), string)

        self.put_option("sort", SortOption(), lambda reader: not reader.senderOnly and not reader.hasSorter, Text.translatable("argument.entity.options.sort.description"))


        # ---------------------------------------------------------------------------------

        class GamemodeOption(SelectorHandler):
            def handle(reader: EntitySelectorReader):
                def _suggest(builder: SuggestionsBuilder, consumer):
                    string = builder.get_remaining().lower()
                    bl = reader.excludesGameMode
                    bl2 = True
                    if string != "":
                        if string[0] == '!':
                            bl = False
                            string = string[1:]

                    var6 = [n for n in GameMode]
                    for gameMode in var6:
                        if gameMode.value.lower().startswith(string):
                            if bl2:
                                builder.suggest("!" + gameMode.value)

                            if bl:
                                builder.suggest(gameMode.value)

                    return builder.build_async()


                i = reader.get_reader().get_cursor()
                bl = reader.read_negation_character()
                if reader.excludesGameMode and not bl:
                    reader.get_reader().set_cursor(i)
                    raise INAPPLICABLE_OPTION_EXCEPTION.create_with_context(reader.get_reader(), "gamemode")
                else:
                    string = reader.get_reader().read_unquoted_string()
                    gameMode = next(iter(g for g in GameMode if g == string), None)
                    if gameMode is None:
                        reader.get_reader().set_cursor(i)
                        raise INVALID_MODE_EXCEPTION.create_with_context(reader.get_reader(), string)
                    else:
                        def _predicate(entity: Entity) -> bool:
                            if not isinstance(entity, ServerPlayerEntity):
                                return False
                            else:
                                gameMode2 = entity.interactionManager.getGameMode()
                                return gameMode2 != gameMode if not bl else gameMode2 == gameMode

                        reader.includesNonPlayers = False
                        reader.predicate = _predicate
                        if bl:
                            reader.excludesGameMode = True
                        else:
                            reader.selectsGameMode = True

        self.put_option("gamemdoe", GamemodeOption(), lambda reader: not reader.selectsGameMode, Text.translatable("argument.entity.options.gamemode.description"))

        class TeamOption(SelectorHandler):
            def handle(reader: EntitySelectorReader):
                bl = reader.read_negation_character()
                string = reader.get_reader().read_unquoted_string()
                def _predicate(entity: Entity):
                    if not isinstance(entity, LivingEntity):
                        return False
                    else:
                        abstractTeam = entity.get_scoreboard_team()
                        string2 = "" if abstractTeam == None else abstractTeam.get_name()
                        return (string2 == string) != bl

                if bl:
                    reader.excludesTeam = True
                else:
                    reader.selectsTeam = True


        self.put_option("team", TeamOption(), lambda reader: not reader.selectsTeam, Text.translatable("argument.entity.options.team.description"))

        class TypeOption(SelectorHandler):
            def handle(reader: EntitySelectorReader):
                def _predicate(builder: SuggestionsBuilder, consumer):
                    CommandSource.suggest_identifiers(Registries.ENTITY_TYPE.get_ids(), builder, "!")
                    CommandSource.suggest_identifiers(Registries.ENTITY_TYPE.streamTags().map(TagKey::id), builder, "!#")
                    if not reader.excludesEntityType():
                        CommandSource.suggest_identifiers(Registries.ENTITY_TYPE.get_ids(), builder)
                        CommandSource.suggest_identifiers(Registries.ENTITY_TYPE.streamTags().map(TagKey::id), builder, String.valueOf('#'))

                    return builder.build_async()

                i = reader.get_reader().get_cursor()
                bl = reader.read_negation_character()
                if reader.excludesEntityType and not bl:
                    reader.get_reader().set_cursor(i)
                    raise INAPPLICABLE_OPTION_EXCEPTION.create_with_context(reader.get_reader(), "type")
                else:
                    if bl:
                        reader.excludesEntityType = True

                    if reader.read_tag_character():
                        tag_key =


            putOption("type", lambda reader: (
                reader.setSuggestionProvider((builder, consumer) -> {

                })
                int i = reader.get_reader().getCursor()
                boolean bl = reader.readNegationCharacter()
                if (reader.excludesEntityType() && !bl) {
                    reader.get_reader().set_cursor(i)
                    throw
                } else {
                    if (bl) {
                        reader.setExcludesEntityType()
                    }

                    if (reader.readTagCharacter()) {
                        TagKey<EntityType<?>> tagKey = TagKey.of(RegistryKeys.ENTITY_TYPE, Identifier.fromCommandInput(reader.get_reader()))
                        reader.setPredicate((entity) -> {
                            return entity.getType().isIn(tagKey) != bl
                        })
                    } else {
                        Identifier identifier = Identifier.fromCommandInput(reader.get_reader())
                        EntityType<?> entityType = (EntityType)Registries.ENTITY_TYPE.getOrEmpty(identifier).orElseThrow(() -> {
                            reader.get_reader().set_cursor(i)
                            return INVALID_TYPE_EXCEPTION.create_with_context(reader.get_reader(), identifier.toString())
                        })
                        if (Objects.equals(EntityType.PLAYER, entityType) && !bl) {
                            reader.setIncludesNonPlayers(false)
                        }

                        reader.setPredicate((entity) -> {
                            return Objects.equals(entityType, entity.getType()) != bl
                        })
                        if (!bl) {
                            reader.setEntityType(entityType)
                        }
                    }

                }

            }, lambda reader: (
                return !reader.selectsEntityType()
            }, Text.translatable("argument.entity.options.type.description"))

            putOption("tag", lambda reader: (
                boolean bl = reader.readNegationCharacter()
                String string = reader.get_reader().readUnquotedString()
                reader.setPredicate((entity) -> {
                    if ("".equals(string)) {
                        return entity.getCommandTags().isEmpty() != bl
                    } else {
                        return entity.getCommandTags().contains(string) != bl
                    }
                })

            }, lambda reader: (
                return True
            }, Text.translatable("argument.entity.options.tag.description"))

            putOption("nbt", lambda reader: (
                boolean bl = reader.readNegationCharacter()
                NbtCompound nbtCompound = (StringNbtReader(reader.get_reader())).parseCompound()
                reader.setPredicate((entity) -> {
                    NbtCompound nbtCompound2 = entity.writeNbt(NbtCompound())
                    if (entity instanceof ServerPlayerEntity) {
                        ItemStack itemStack = ((ServerPlayerEntity)entity).getInventory().getMainHandStack()
                        if (!itemStack.isEmpty()) {
                            nbtCompound2.put("SelectedItem", itemStack.writeNbt(NbtCompound()))
                        }
                    }

                    return NbtHelper.matches(nbtCompound, nbtCompound2, True) != bl
                })

            }, lambda reader: (
                return True
            }, Text.translatable("argument.entity.options.nbt.description"))

            putOption("scores", lambda reader: (
                StringReader stringReader = reader.get_reader()
                Map<String, NumberRange.IntRange> map = Maps.newHashMap()
                stringReader.expect('{')
                stringReader.skipWhitespace()

                while(stringReader.canRead() && stringReader.peek() != '}') {
                    stringReader.skipWhitespace()
                    String string = stringReader.readUnquotedString()
                    stringReader.skipWhitespace()
                    stringReader.expect('=')
                    stringReader.skipWhitespace()
                    NumberRange.IntRange intRange = IntRange.parse(stringReader)
                    map.put(string, intRange)
                    stringReader.skipWhitespace()
                    if (stringReader.canRead() && stringReader.peek() == ',') {
                        stringReader.skip()
                    }
                }

                stringReader.expect('}')
                if (!map.isEmpty()) {
                    reader.setPredicate((entity) -> {
                        Scoreboard scoreboard = entity.getServer().getScoreboard()
                        Iterator var3 = map.entrySet().iterator()

                        Map.Entry entry
                        ReadableScoreboardScore readableScoreboardScore
                        do {
                            if (!var3.hasNext()) {
                                return True
                            }

                            entry = (Map.Entry)var3.next()
                            ScoreboardObjective scoreboardObjective = scoreboard.getNullableObjective((String)entry.getKey())
                            if (scoreboardObjective == null) {
                                return false
                            }

                            readableScoreboardScore = scoreboard.getScore(entity, scoreboardObjective)
                            if (readableScoreboardScore == null) {
                                return false
                            }
                        } while(((NumberRange.IntRange)entry.getValue()).test(readableScoreboardScore.getScore()))

                        return false
                    })
                }

                reader.setSelectsScores(True)

            }, lambda reader: (
                return !reader.selectsScores()
            }, Text.translatable("argument.entity.options.scores.description"))

            putOption("advancements", lambda reader: (
                StringReader stringReader = reader.get_reader()
                Map<Identifier, Predicate<AdvancementProgress>> map = Maps.newHashMap()
                stringReader.expect('{')
                stringReader.skipWhitespace()

                while(stringReader.canRead() && stringReader.peek() != '}') {
                    stringReader.skipWhitespace()
                    Identifier identifier = Identifier.fromCommandInput(stringReader)
                    stringReader.skipWhitespace()
                    stringReader.expect('=')
                    stringReader.skipWhitespace()
                    if (stringReader.canRead() && stringReader.peek() == '{') {
                        Map<String, Predicate<CriterionProgress>> map2 = Maps.newHashMap()
                        stringReader.skipWhitespace()
                        stringReader.expect('{')
                        stringReader.skipWhitespace()

                        while(stringReader.canRead() && stringReader.peek() != '}') {
                            stringReader.skipWhitespace()
                            String string = stringReader.readUnquotedString()
                            stringReader.skipWhitespace()
                            stringReader.expect('=')
                            stringReader.skipWhitespace()
                            boolean bl = stringReader.readBoolean()
                            map2.put(string, (criterionProgress) -> {
                                return criterionProgress.isObtained() == bl
                            })
                            stringReader.skipWhitespace()
                            if (stringReader.canRead() && stringReader.peek() == ',') {
                                stringReader.skip()
                            }
                        }

                        stringReader.skipWhitespace()
                        stringReader.expect('}')
                        stringReader.skipWhitespace()
                        map.put(identifier, (advancementProgress) -> {
                            Iterator var2 = map2.entrySet().iterator()

                            Map.Entry entry
                            CriterionProgress criterionProgress
                            do {
                                if (!var2.hasNext()) {
                                    return True
                                }

                                entry = (Map.Entry)var2.next()
                                criterionProgress = advancementProgress.getCriterionProgress((String)entry.getKey())
                            } while(criterionProgress != null && ((Predicate)entry.getValue()).test(criterionProgress))

                            return false
                        })
                    } else {
                        boolean bl2 = stringReader.readBoolean()
                        map.put(identifier, (advancementProgress) -> {
                            return advancementProgress.isDone() == bl2
                        })
                    }

                    stringReader.skipWhitespace()
                    if (stringReader.canRead() && stringReader.peek() == ',') {
                        stringReader.skip()
                    }
                }

                stringReader.expect('}')
                if (!map.isEmpty()) {
                    reader.setPredicate((entity) -> {
                        if (!(entity instanceof ServerPlayerEntity serverPlayerEntity)) {
                            return false
                        } else {
                            PlayerAdvancementTracker playerAdvancementTracker = serverPlayerEntity.getAdvancementTracker()
                            ServerAdvancementLoader serverAdvancementLoader = serverPlayerEntity.getServer().getAdvancementLoader()
                            Iterator var5 = map.entrySet().iterator()

                            Map.Entry entry
                            AdvancementEntry advancementEntry
                            do {
                                if (!var5.hasNext()) {
                                    return True
                                }

                                entry = (Map.Entry)var5.next()
                                advancementEntry = serverAdvancementLoader.get((Identifier)entry.getKey())
                            } while(advancementEntry != null && ((Predicate)entry.getValue()).test(playerAdvancementTracker.getProgress(advancementEntry)))

                            return false
                        }
                    })
                    reader.setIncludesNonPlayers(false)
                }

                reader.setSelectsAdvancements(True)

            }, lambda reader: (
                return !reader.selectsAdvancements()
            }, Text.translatable("argument.entity.options.advancements.description"))

            putOption("predicate", lambda reader: (
                boolean bl = reader.readNegationCharacter()
                Identifier identifier = Identifier.fromCommandInput(reader.get_reader())
                reader.setPredicate((entity) -> {
                    if (!(entity.getWorld() instanceof ServerWorld)) {
                        return false
                    } else {
                        ServerWorld serverWorld = (ServerWorld)entity.getWorld()
                        LootCondition lootCondition = (LootCondition)serverWorld.getServer().getLootManager().getElement(LootDataType.PREDICATES, identifier)
                        if (lootCondition == null) {
                            return false
                        } else {
                            LootContextParameterSet lootContextParameterSet = (LootContextParameterSet.Builder(serverWorld)).add(LootContextParameters.THIS_ENTITY, entity).add(LootContextParameters.ORIGIN, entity.getPos()).build(LootContextTypes.SELECTOR)
                            LootContext lootContext = (LootContext.Builder(lootContextParameterSet)).build(Optional.empty())
                            lootContext.markActive(LootContext.predicate(lootCondition))
                            return bl ^ lootCondition.test(lootContext)
                        }
                    }
                })

            }, lambda reader: (
                return True
            }, Text.translatable("argument.entity.options.predicate.description"))


    def description(self) -> Text:
        return self.description