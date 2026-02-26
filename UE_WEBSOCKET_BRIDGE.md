# Unreal Engine WebSocket Bridge — clyde-cabin-llm

## Purpose

A C++ Actor Component that opens a WebSocket connection to the Python agent, parses incoming JSON commands, and fires Blueprint-callable events. Blueprint then calls the runtime property setters you've already built for VR interaction.

Sequencer is untouched — it remains useful for pre-viz and rendering. At runtime, properties are driven directly.

---

## Architecture

```
Python Agent (ws://localhost:8765)
        ↓ JSON command
UAgentBridgeComponent (C++)
        ↓ multicast delegate
Blueprint event handlers
        ↓
Set properties on cabin Actors (lights, display, climate, audio)
```

---

## Module Setup

Add to `clyde-cabin-llm.Build.cs`:

```csharp
PublicDependencyModuleNames.AddRange(new string[] {
    "Core",
    "CoreUObject",
    "Engine",
    "WebSockets",
    "Json",
    "JsonUtilities"
});
```

---

## Header — `AgentBridgeComponent.h`

```cpp
#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "IWebSocket.h"
#include "AgentBridgeComponent.generated.h"

// --- Delegate signatures (Blueprint-assignable) ---

DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(
    FOnLightsCommand,
    int32, Brightness,
    FString, ColorTemp
);

DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(
    FOnClimateCommand,
    int32, TempF,
    FString, FanSpeed
);

DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(
    FOnAudioCommand,
    FString, Action,
    FString, Genre
);

DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(
    FOnDisplayCommand,
    FString, Layout,
    FString, DataJson   // pass raw JSON string, parse in Blueprint or a helper
);

DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(
    FOnAgentConnected,
    bool, bConnected
);

// ---

UCLASS(ClassGroup=(ClydeAgent), meta=(BlueprintSpawnableComponent))
class CLYDE_CABIN_LLM_API UAgentBridgeComponent : public UActorComponent
{
    GENERATED_BODY()

public:
    UAgentBridgeComponent();

    // --- Config ---
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Agent Bridge")
    FString ServerURL = TEXT("ws://127.0.0.1:8765");

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Agent Bridge")
    bool bAutoConnectOnBeginPlay = true;

    // --- Blueprint Events ---
    UPROPERTY(BlueprintAssignable, Category="Agent Bridge")
    FOnLightsCommand OnLightsCommand;

    UPROPERTY(BlueprintAssignable, Category="Agent Bridge")
    FOnClimateCommand OnClimateCommand;

    UPROPERTY(BlueprintAssignable, Category="Agent Bridge")
    FOnAudioCommand OnAudioCommand;

    UPROPERTY(BlueprintAssignable, Category="Agent Bridge")
    FOnDisplayCommand OnDisplayCommand;

    UPROPERTY(BlueprintAssignable, Category="Agent Bridge")
    FOnAgentConnected OnConnectionChanged;

    // --- Blueprint Callable ---
    UFUNCTION(BlueprintCallable, Category="Agent Bridge")
    void Connect();

    UFUNCTION(BlueprintCallable, Category="Agent Bridge")
    void Disconnect();

    UFUNCTION(BlueprintCallable, Category="Agent Bridge")
    void SendMessage(const FString& JsonString);

    UFUNCTION(BlueprintPure, Category="Agent Bridge")
    bool IsConnected() const { return bIsConnected; }

protected:
    virtual void BeginPlay() override;
    virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;

private:
    TSharedPtr<IWebSocket> WebSocket;
    bool bIsConnected = false;

    void InitWebSocket();
    void HandleMessage(const FString& Message);
};
```

---

## Implementation — `AgentBridgeComponent.cpp`

```cpp
#include "AgentBridgeComponent.h"
#include "WebSocketsModule.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

UAgentBridgeComponent::UAgentBridgeComponent()
{
    PrimaryComponentTick.bCanEverTick = false;
}

void UAgentBridgeComponent::BeginPlay()
{
    Super::BeginPlay();
    if (bAutoConnectOnBeginPlay)
    {
        Connect();
    }
}

void UAgentBridgeComponent::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
    Disconnect();
    Super::EndPlay(EndPlayReason);
}

void UAgentBridgeComponent::Connect()
{
    if (!FModuleManager::Get().IsModuleLoaded("WebSockets"))
    {
        FModuleManager::Get().LoadModule("WebSockets");
    }
    InitWebSocket();
}

void UAgentBridgeComponent::Disconnect()
{
    if (WebSocket.IsValid() && WebSocket->IsConnected())
    {
        WebSocket->Close();
    }
}

void UAgentBridgeComponent::SendMessage(const FString& JsonString)
{
    if (WebSocket.IsValid() && WebSocket->IsConnected())
    {
        WebSocket->Send(JsonString);
    }
}

void UAgentBridgeComponent::InitWebSocket()
{
    WebSocket = FWebSocketsModule::Get().CreateWebSocket(ServerURL, TEXT("ws"));

    WebSocket->OnConnected().AddLambda([this]()
    {
        bIsConnected = true;
        OnConnectionChanged.Broadcast(true);
        UE_LOG(LogTemp, Log, TEXT("AgentBridge: Connected to %s"), *ServerURL);
    });

    WebSocket->OnConnectionError().AddLambda([this](const FString& Error)
    {
        bIsConnected = false;
        OnConnectionChanged.Broadcast(false);
        UE_LOG(LogTemp, Warning, TEXT("AgentBridge: Connection error — %s"), *Error);
    });

    WebSocket->OnClosed().AddLambda([this](int32 Code, const FString& Reason, bool bWasClean)
    {
        bIsConnected = false;
        OnConnectionChanged.Broadcast(false);
        UE_LOG(LogTemp, Log, TEXT("AgentBridge: Closed (%d) %s"), Code, *Reason);
    });

    WebSocket->OnMessage().AddLambda([this](const FString& Message)
    {
        HandleMessage(Message);
    });

    WebSocket->Connect();
}

void UAgentBridgeComponent::HandleMessage(const FString& Message)
{
    TSharedPtr<FJsonObject> Root;
    TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Message);

    if (!FJsonSerializer::Deserialize(Reader, Root) || !Root.IsValid())
    {
        UE_LOG(LogTemp, Warning, TEXT("AgentBridge: Failed to parse JSON — %s"), *Message);
        return;
    }

    FString Command;
    if (!Root->TryGetStringField(TEXT("command"), Command))
    {
        UE_LOG(LogTemp, Warning, TEXT("AgentBridge: No 'command' field in message"));
        return;
    }

    if (Command == TEXT("set_lights"))
    {
        int32 Brightness = Root->GetIntegerField(TEXT("brightness"));
        FString ColorTemp = Root->GetStringField(TEXT("color_temp"));
        OnLightsCommand.Broadcast(Brightness, ColorTemp);
    }
    else if (Command == TEXT("set_climate"))
    {
        int32 TempF = Root->GetIntegerField(TEXT("temp_f"));
        FString FanSpeed = Root->GetStringField(TEXT("fan_speed"));
        OnClimateCommand.Broadcast(TempF, FanSpeed);
    }
    else if (Command == TEXT("set_audio"))
    {
        FString Action = Root->GetStringField(TEXT("action"));
        FString Genre = Root->GetStringField(TEXT("genre"));
        OnAudioCommand.Broadcast(Action, Genre);
    }
    else if (Command == TEXT("send_display"))
    {
        FString Layout = Root->GetStringField(TEXT("layout"));
        // Re-serialize the data sub-object for Blueprint to handle
        TSharedPtr<FJsonObject> DataObj = Root->GetObjectField(TEXT("data"));
        FString DataJson;
        TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&DataJson);
        FJsonSerializer::Serialize(DataObj.ToSharedRef(), Writer);
        OnDisplayCommand.Broadcast(Layout, DataJson);
    }
    else
    {
        UE_LOG(LogTemp, Warning, TEXT("AgentBridge: Unknown command — %s"), *Command);
    }
}
```

---

## JSON Message Format (Python → UE)

All messages from the Python agent follow this structure:

```json
{ "command": "set_lights", "brightness": 60, "color_temp": "warm" }
{ "command": "set_climate", "temp_f": 72, "fan_speed": "low" }
{ "command": "set_audio", "action": "play", "genre": "ambient" }
{ "command": "send_display", "layout": "arrival", "data": { "stop": "Civic Center", "eta": "2 min" } }
```

---

## Blueprint Wiring

1. Add `AgentBridgeComponent` to your cabin manager Actor
2. In the Event Graph, bind to the four delegates:
   - `OnLightsCommand` → call your existing light property setters
   - `OnClimateCommand` → call climate setters
   - `OnAudioCommand` → call audio setters
   - `OnDisplayCommand` → switch on Layout string → update display Actor/widget
3. `OnConnectionChanged` → optionally drive a debug indicator in the scene

`bAutoConnectOnBeginPlay = true` so it connects when you hit Play. Set `ServerURL` in the component Details panel — default is `ws://127.0.0.1:8765`.

---

## Python Agent — Sending Commands

In `llm.py`, after a tool call resolves, send to UE via the existing WebSocket server. Add a send helper:

```python
async def send_to_ue(ws_clients: set, command: dict):
    if ws_clients:
        message = json.dumps(command)
        await asyncio.gather(*[client.send(message) for client in ws_clients])
```

Example tool call resolution:

```python
# set_lights tool handler
async def handle_set_lights(brightness: int, color_temp: str, ws_clients: set):
    await send_to_ue(ws_clients, {
        "command": "set_lights",
        "brightness": brightness,
        "color_temp": color_temp
    })
    # also POST to mock vehicle API
    requests.post("http://localhost:8001/lights", json={...})
```

---

## File Placement

```
clyde-cabin-llm/
└── Source/
    └── clyde_cabin_llm/
        ├── AgentBridgeComponent.h
        └── AgentBridgeComponent.cpp
```

Regenerate project files after adding, then build from Xcode or the UE editor.
