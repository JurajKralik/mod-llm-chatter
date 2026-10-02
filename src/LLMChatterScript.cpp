#include "LLMChatterSimulation.h"
/*
 * mod-llm-chatter - registration coordinator
 */

#include "LLMChatterBG.h"
#include "LLMChatterGuild.h"
#include "LLMChatterGroup.h"
#include "LLMChatterRaid.h"
#include "LLMChatterShared.h"

void AddLLMChatterCommandScripts();

void AddLLMChatterScripts()
{
    AddLLMChatterSimulationScripts();
    AddLLMChatterWorldScripts();
    AddLLMChatterGuildScripts();
    AddLLMChatterGroupScripts();
    AddLLMChatterPlayerScripts();
    AddLLMChatterBGScripts();
    AddLLMChatterRaidScripts();
    AddLLMChatterCommandScripts();
}
