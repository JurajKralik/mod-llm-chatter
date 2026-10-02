#ifndef MOD_LLM_CHATTER_SIMULATION_H
#define MOD_LLM_CHATTER_SIMULATION_H

#include "Define.h"
#include <string>
#include <vector>

class Player;
void LoadSimulationConfig();
bool SimulationEnabled();
float SimulationRadius();
void QueueSimulationLocal(Player* player, std::string const& message);
void SimulationTick();
void DeliverSimulationMessage(uint32 id, uint32 botGuid, uint32 playerGuid,
    std::string const& message, std::string const& channel);
void AddLLMChatterSimulationScripts();
std::vector<Player*> GetSimulationNearbyBots(Player* player, float radius);

#endif
