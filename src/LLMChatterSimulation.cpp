/* Player simulation adapter. All game mutations stay on the world thread. */
#include "LLMChatterSimulation.h"
#include "LLMChatterConfig.h"
#include "LLMChatterShared.h"
#include "Chat.h"
#include "Config.h"
#include "DatabaseEnv.h"
#include "Group.h"
#include "GroupMgr.h"
#include "Guild.h"
#include "ObjectAccessor.h"
#include "Player.h"
#include "PlayerbotAI.h"
#include "Playerbots.h"
#include "RandomPlayerbotMgr.h"
#include "ScriptMgr.h"
#include "WorldSession.h"

#include <algorithm>
#include <ctime>
#include <map>
#include <set>
#include <sstream>

namespace
{
bool enabled = false;
bool behavior = false;
float radius = 40.0f;
uint32 maxCandidates = 24;
uint32 gapSeconds = 3;
uint32 actionLeaseSeconds = 1800;
std::map<std::string, time_t> lastCapture;
std::map<uint32, time_t> lastHeard;

Player* Resolve(uint32 guid)
{
    return ObjectAccessor::FindPlayer(ObjectGuid::Create<HighGuid::Player>(guid));
}

bool Real(Player* player)
{
    return player && player->IsInWorld() && !IsPlayerBot(player);
}

bool Candidate(Player* bot, Player* observer)
{
    return bot && bot->IsInWorld() && IsPlayerBot(bot)
        && bot->GetTeamId() == observer->GetTeamId()
        && bot->GetSession() && !bot->GetSession()->PlayerLoading();
}

// Connected observer footprints prevent duplicate local scenes near two players.
// This walks real players, never the realm-wide bot population.
std::string LocalContext(Player* player)
{
    auto realPlayers = sRandomPlayerbotMgr.GetPlayers();
    std::vector<Player*> cluster{player};
    std::set<uint32> visited{player->GetGUID().GetCounter()};
    for (size_t i = 0; i < cluster.size(); ++i)
    {
        for (Player* other : realPlayers)
        {
            if (!Real(other) || other->GetTeamId() != player->GetTeamId()
                || visited.count(other->GetGUID().GetCounter())
                || !cluster[i]->IsWithinDistInMap(other, radius * 2.0f))
                continue;
            visited.insert(other->GetGUID().GetCounter());
            cluster.push_back(other);
        }
    }
    return "sim:local:" + std::to_string(player->GetMapId()) + ":"
        + std::to_string(player->GetInstanceId()) + ":" + std::to_string(*visited.begin());
}

bool Owns(Player* bot, Player* player)
{
    QueryResult result = CharacterDatabase.Query(
        "SELECT player_guid,group_id FROM llm_sim_action_lease WHERE bot_guid = {}",
        bot->GetGUID().GetCounter());
    return result && bot->GetGroup()
        && result->Fetch()[0].Get<uint32>() == player->GetGUID().GetCounter()
        && result->Fetch()[1].Get<uint32>() == bot->GetGroup()->GetGUID().GetCounter();
}

void Queue(Player* player, std::vector<Player*> candidates, std::string const& message,
    std::string const& channel, std::string const& context, uint32 direct = 0)
{
    if (!SimulationEnabled() || !Real(player) || candidates.empty())
        return;
    time_t now = time(nullptr);
    // Ingestion coalescing only; final pacing is tied to actual delivery.
    std::string captureKey = context + (message.empty() ? ":ambient" : ":" + std::to_string(player->GetGUID().GetCounter()));
    auto prior = lastCapture.find(captureKey);
    if (prior != lastCapture.end() && now - prior->second < (message.empty() ? 25 : 1))
        return;
    lastCapture[captureKey] = now;

    // Preserve named candidates ahead of a bounded shortlist.
    std::string lower = message;
    std::transform(lower.begin(), lower.end(), lower.begin(), [](unsigned char c) { return std::tolower(c); });
    auto named = [&](Player* bot)
    {
        std::string name = bot->GetName();
        std::transform(name.begin(), name.end(), name.begin(), [](unsigned char c) { return std::tolower(c); });
        return lower.find(name) != std::string::npos || bot->GetGUID().GetCounter() == direct;
    };
    std::stable_partition(candidates.begin(), candidates.end(), named);
    std::ostringstream data;
    data << "{\"simulation_version\":1,\"context_key\":\"" << JsonEscape(context)
         << "\",\"channel\":\"" << channel << "\",\"player_guid\":" << player->GetGUID().GetCounter()
         << ",\"player_name\":\"" << JsonEscape(player->GetName()) << "\",\"player_message\":\""
         << JsonEscape(message) << "\",\"map_id\":" << player->GetMapId()
         << ",\"instance_id\":" << player->GetInstanceId() << ",\"direct_guid\":" << direct
         << ",\"group_id\":" << (player->GetGroup() ? player->GetGroup()->GetGUID().GetCounter() : 0)
         << ",\"guild_id\":" << player->GetGuildId()
         << ",\"zone_name\":\"" << JsonEscape(GetZoneName(player->GetZoneId())) << "\",\"candidates\":[";
    uint32 count = 0;
    for (Player* bot : candidates)
    {
        if (!Candidate(bot, player))
            continue;
        if (count >= maxCandidates)
            break;
        if (count++)
            data << ',';
        data << "{\"guid\":" << bot->GetGUID().GetCounter() << ",\"name\":\""
             << JsonEscape(bot->GetName()) << "\",\"level\":" << uint32(bot->GetLevel())
             << ",\"class\":\"" << GetChatterClassName(bot->getClass())
             << "\",\"combat\":" << (bot->IsInCombat() ? "true" : "false") << ",\"actions\":[";
        if (behavior && !bot->IsInCombat() && bot->IsAlive() && !bot->IsInFlight()
            && player->IsWithinDistInMap(bot, radius) && sRandomPlayerbotMgr.IsRandomBot(bot))
        {
            if (!bot->GetGroup())
                data << "\"follow_player\"";
            else if (Owns(bot, player))
                data << "\"follow_player\",\"stay_here\",\"resume_autonomous\"";
        }
        data << "]}";
    }
    data << "]}";
    if (!count)
        return;
    QueueChatterEvent("proximity_player_say", "player", player->GetZoneId(), player->GetMapId(),
        message.empty() ? 2 : 9, context, 0, "", player->GetGUID().GetCounter(), player->GetName(),
        0, EscapeString(data.str()), 0, 90, false);
}

std::string ExecuteIntent(Player* bot, Player* player, std::string const& intent)
{
    if (intent == "none")
        return "";
    if (!behavior)
        return "behavior_disabled";
    if (intent != "follow_player" && intent != "stay_here" && intent != "resume_autonomous")
        return "unsupported_action";
    if (!sRandomPlayerbotMgr.IsRandomBot(bot))
        return "not_random_bot";
    PlayerbotAI* ai = GET_PLAYERBOT_AI(bot);
    if (!ai || (ai->GetMaster() && ai->GetMaster() != player))
        return "owned_by_other_player";
    bool owned = Owns(bot, player);
    if (intent == "resume_autonomous")
    {
        if (!owned)
            return "not_simulation_owned";
        ai->SetMaster(nullptr);
        if (Group* group = bot->GetGroup())
            group->RemoveMember(bot->GetGUID());
        ai->ResetStrategies();
        CharacterDatabase.DirectExecute("DELETE FROM llm_sim_action_lease WHERE bot_guid = {}",
            bot->GetGUID().GetCounter());
        return "";
    }
    if (!bot->IsAlive() || bot->IsInCombat() || bot->IsInFlight())
        return "bot_busy";
    if (!player->IsWithinDistInMap(bot, radius))
        return "target_out_of_range";
    if (intent == "stay_here")
    {
        if (!owned)
            return "not_simulation_owned";
        ai->ChangeStrategy("-follow,+stay", BOT_STATE_NON_COMBAT);
        ai->DoSpecificAction("stay", Event(), true);
        return ai->HasStrategy("stay", BOT_STATE_NON_COMBAT) ? "" : "strategy_failed";
    }
    if (bot->GetGroup() && !owned)
        return "already_grouped";
    if (owned && bot->GetGroup() != player->GetGroup())
        return "group_changed";
    if (!bot->GetGroup())
    {
        Group* group = player->GetGroup();
        if (group && (group->IsFull() || group->isRaidGroup() || group->GetLeaderGUID() != player->GetGUID()))
            return "group_unavailable";
        if (!group)
        {
            group = new Group();
            if (!group->Create(player))
            {
                delete group;
                return "group_create_failed";
            }
            sGroupMgr->AddGroup(group);
        }
        if (!group->AddMember(bot))
            return "group_join_failed";
    }
    // Only fixed literals reach PlayerBots; no model text is a command.
    ai->SetMaster(player);
    ai->ResetStrategies();
    ai->ChangeStrategy("-rpg,-grind,-stay,+follow", BOT_STATE_NON_COMBAT);
    ai->DoSpecificAction("follow", Event(), true);
    if (!ai->HasStrategy("follow", BOT_STATE_NON_COMBAT))
        return "strategy_failed";
    CharacterDatabase.DirectExecute(
        "INSERT INTO llm_sim_action_lease(bot_guid,player_guid,group_id,expires_at) VALUES ({},{},{},"
        "UTC_TIMESTAMP()+INTERVAL {} SECOND) ON DUPLICATE KEY UPDATE expires_at=VALUES(expires_at),"
        "group_id=VALUES(group_id)",
        bot->GetGUID().GetCounter(), player->GetGUID().GetCounter(),
        bot->GetGroup()->GetGUID().GetCounter(), actionLeaseSeconds);
    if (!Owns(bot, player))
    {
        ai->SetMaster(nullptr);
        if (Group* group = bot->GetGroup())
            group->RemoveMember(bot->GetGUID());
        ai->ResetStrategies();
        return "ownership_persistence_failed";
    }
    return "";
}
}

void LoadSimulationConfig()
{
    enabled = sConfigMgr->GetOption<bool>("LLMChatter.Simulation.Enable", false);
    behavior = sConfigMgr->GetOption<bool>("LLMChatter.Simulation.Behavior.Enable", false);
    radius = std::clamp(sConfigMgr->GetOption<float>("LLMChatter.Simulation.ProximityRadius", 40.0f), 1.0f, 100.0f);
    maxCandidates = std::clamp(sConfigMgr->GetOption<uint32>("LLMChatter.Simulation.Conversation.MaxCandidates", 24), 1u, 40u);
    gapSeconds = std::clamp(sConfigMgr->GetOption<uint32>("LLMChatter.Simulation.Conversation.MinVisibleLineGap", 3), 1u, 60u);
    actionLeaseSeconds = std::clamp(sConfigMgr->GetOption<uint32>("LLMChatter.Simulation.Behavior.LeaseSeconds", 1800), 30u, 7200u);
}

bool SimulationEnabled()
{
    return enabled && sLLMChatterConfig->IsEnabled();
}

float SimulationRadius()
{
    return radius;
}

void QueueSimulationLocal(Player* player, std::string const& message)
{
    if (!SimulationEnabled() || !Real(player))
        return;
    Queue(player, GetSimulationNearbyBots(player, radius), message, "say", LocalContext(player));
}

void DeliverSimulationMessage(uint32 id, uint32 botGuid, uint32 playerGuid,
    std::string const& message, std::string const& channel)
{
    QueryResult result = CharacterDatabase.Query(
        "SELECT event_id,context_key,map_id,instance_id,group_id,guild_id,intent,"
        "expires_at>UTC_TIMESTAMP() FROM llm_sim_outbox WHERE message_id={} AND status='pending'", id);
    if (!result)
        return;
    Field* fields = result->Fetch();
    uint32 eventId = fields[0].Get<uint32>();
    std::string context = fields[1].Get<std::string>();
    std::string intent = fields[6].Get<std::string>();
    std::string reason;
    Player* bot = Resolve(botGuid);
    Player* player = Resolve(playerGuid);
    if (!SimulationEnabled())
        reason = "simulation_disabled";
    else if (!fields[7].Get<bool>())
        reason = "expired";
    else if (!Real(player) || !Candidate(bot, player))
        reason = "participant_missing";
    else if (channel == "say" && (!bot->IsAlive() || bot->GetMapId() != fields[2].Get<uint32>()
        || bot->GetInstanceId() != fields[3].Get<uint32>() || !player->IsWithinDistInMap(bot, radius)))
        reason = "local_context_changed";
    else if ((channel == "party" || channel == "raid" || channel == "battleground")
        && (!bot->GetGroup() || bot->GetGroup() != player->GetGroup()
            || bot->GetGroup()->GetGUID().GetCounter() != fields[4].Get<uint32>()))
        reason = "group_changed";
    else if (channel != "say" && channel != "whisper" && channel != "party" && channel != "raid" && channel != "battleground")
        reason = "unsupported_channel";
    if (reason.empty() && channel == "battleground"
        && (!bot->InBattleground() || bot->GetBattleground() != player->GetBattleground()))
        reason = "battleground_changed";
    if (reason.empty() && channel == "raid" && !bot->GetGroup()->isRaidGroup())
        reason = "raid_changed";

    // Recheck the lease even after a delayed world tick/restart.
    if (reason.empty())
    {
        QueryResult lease = CharacterDatabase.Query(
            "SELECT event_id FROM llm_sim_context WHERE context_key='{}' AND lease_until>UTC_TIMESTAMP()",
            EscapeString(context));
        if (!lease || lease->Fetch()[0].Get<uint32>() != eventId)
            reason = "context_superseded";
    }
    // Final visible gate also covers context merges while generation was in flight.
    if (reason.empty() && channel == "say")
    {
        for (Player* observer : sRandomPlayerbotMgr.GetPlayers())
        {
            if (Real(observer) && observer->IsWithinDistInMap(bot, radius)
                && lastHeard[observer->GetGUID().GetCounter()] + gapSeconds > time(nullptr))
            {
                CharacterDatabase.DirectExecute("UPDATE llm_chatter_messages SET delivered=0,deliver_at=NOW()+INTERVAL 1 SECOND WHERE id={}", id);
                return;
            }
        }
    }
    if (reason.empty())
        reason = ExecuteIntent(bot, player, intent);
    bool sent = false;
    if (reason.empty())
    {
        PlayerbotAI* ai = GET_PLAYERBOT_AI(bot);
        if (channel == "say")
            sent = ai->Say(message);
        else if (channel == "whisper")
            sent = ai->Whisper(message, player->GetName());
        else
        {
            WorldPacket packet;
            ChatHandler::BuildChatPacket(packet, channel == "party" ? CHAT_MSG_PARTY :
                channel == "raid" ? CHAT_MSG_RAID : CHAT_MSG_BATTLEGROUND,
                LANG_UNIVERSAL, bot, nullptr, message);
            if (Group* group = bot->GetGroup())
            {
                group->BroadcastPacket(&packet, false);
                sent = true;
            }
            else if (intent == "resume_autonomous")
            {
                // Releasing ownership may disband the original two-person party.
                // A private acknowledgement remains valid after leaving that group.
                sent = ai->Whisper(message, player->GetName());
                if (sent)
                    CharacterDatabase.DirectExecute(
                        "UPDATE llm_chatter_messages SET channel='whisper' WHERE id={}", id);
            }
        }
        if (!sent)
            reason = "delivery_failed";
        if (sent && channel == "say")
            for (Player* observer : sRandomPlayerbotMgr.GetPlayers())
                if (Real(observer) && observer->IsWithinDistInMap(bot, radius))
                    lastHeard[observer->GetGUID().GetCounter()] = time(nullptr);
    }
    CharacterDatabase.DirectExecute(
        "UPDATE llm_sim_outbox SET status='{}',reason='{}',completed_at=UTC_TIMESTAMP() WHERE message_id={}",
        sent ? "succeeded" : "failed", EscapeString(reason), id);
    CharacterDatabase.DirectExecute(
        "UPDATE llm_chatter_messages SET delivered=1,delivered_at={} WHERE id={}",
        sent ? "NOW()" : "NULL", id);
    CharacterDatabase.DirectExecute(
        "UPDATE llm_sim_speaker SET lease_until=NULL,event_id=NULL,last_visible_at={} "
        "WHERE bot_guid={} AND event_id={}", sent ? "UTC_TIMESTAMP()" : "last_visible_at", botGuid, eventId);
    CharacterDatabase.DirectExecute(
        "UPDATE llm_sim_context SET event_id=NULL,lease_until=NULL,last_speaker={},"
        "next_visible_at=UTC_TIMESTAMP()+INTERVAL {} SECOND WHERE context_key='{}' AND event_id={}",
        sent ? botGuid : 0, gapSeconds, EscapeString(context), eventId);
}

void SimulationTick()
{
    static time_t last = 0;
    static bool wasEnabled = false;
    wasEnabled = wasEnabled || enabled;
    time_t now = time(nullptr);
    if (now - last < 5 || !wasEnabled)
        return;
    last = now;
    for (auto it = lastCapture.begin(); it != lastCapture.end();)
        if (now - it->second > 120)
            it = lastCapture.erase(it);
        else
            ++it;
    for (auto it = lastHeard.begin(); it != lastHeard.end();)
        if (now - it->second > 120)
            it = lastHeard.erase(it);
        else
            ++it;
    QueryResult leases = CharacterDatabase.Query(
        "SELECT bot_guid,player_guid,expires_at<UTC_TIMESTAMP(),group_id FROM llm_sim_action_lease ORDER BY expires_at LIMIT 64");
    if (!leases)
        return;
    do
    {
        Field* row = leases->Fetch();
        Player* bot = Resolve(row[0].Get<uint32>());
        Player* player = Resolve(row[1].Get<uint32>());
        if (Real(player) && !row[2].Get<bool>() && SimulationEnabled())
            continue;
        if (bot)
        {
            if (PlayerbotAI* ai = GET_PLAYERBOT_AI(bot))
            {
                // Never detach a bot that another real master took over.
                if (bot->GetGroup() && bot->GetGroup()->GetGUID().GetCounter() == row[3].Get<uint32>()
                    && (!ai->GetMaster() || ai->GetMaster() == player))
                {
                    ai->SetMaster(nullptr);
                    if (Group* group = bot->GetGroup())
                        group->RemoveMember(bot->GetGUID());
                    ai->ResetStrategies();
                }
            }
        }
        CharacterDatabase.DirectExecute("DELETE FROM llm_sim_action_lease WHERE bot_guid={}", row[0].Get<uint32>());
    } while (leases->NextRow());
}

class LLMChatterSimulationPlayerScript : public PlayerScript
{
public:
    LLMChatterSimulationPlayerScript() : PlayerScript("LLMChatterSimulationPlayerScript",
        {PLAYERHOOK_CAN_PLAYER_USE_PRIVATE_CHAT, PLAYERHOOK_CAN_PLAYER_USE_GROUP_CHAT}) { }

    bool OnPlayerCanUseChat(Player* player, uint32 /*type*/, uint32 language,
        std::string& message, Player* receiver) override
    {
        if (language != LANG_ADDON && Real(player) && Candidate(receiver, player))
            Queue(player, {receiver}, message, "whisper", "sim:whisper:"
                + std::to_string(player->GetGUID().GetCounter()) + ":"
                + std::to_string(receiver->GetGUID().GetCounter()), receiver->GetGUID().GetCounter());
        return true;
    }

    bool OnPlayerCanUseChat(Player* player, uint32 type, uint32 language,
        std::string& message, Group* group) override
    {
        if (!SimulationEnabled() || language == LANG_ADDON || !Real(player) || !group)
            return true;
        std::vector<Player*> bots;
        for (auto const& member : group->GetMemberSlots())
            if (Player* bot = ObjectAccessor::FindPlayer(member.guid))
                if (Candidate(bot, player))
                    bots.push_back(bot);
        std::string channel = type == CHAT_MSG_RAID || type == CHAT_MSG_RAID_LEADER ? "raid" :
            type == CHAT_MSG_BATTLEGROUND || type == CHAT_MSG_BATTLEGROUND_LEADER ? "battleground" : "party";
        Queue(player, bots, message, channel, "sim:group:" + std::to_string(group->GetGUID().GetCounter()));
        return true;
    }
};

void AddLLMChatterSimulationScripts()
{
    new LLMChatterSimulationPlayerScript();
}
