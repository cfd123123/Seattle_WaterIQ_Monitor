package com.example.waterbusiness.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.List;
import java.util.Map;
import lombok.Data;

@Data
@JsonIgnoreProperties(ignoreUnknown = true)
public class AssistantChatResponse {

    private String answer;
    private List<AssistantSourceDto> sources;

    @JsonProperty("tool_calls")
    private List<AssistantToolCallAuditDto> toolCalls;

    @JsonProperty("tool_trace")
    private List<String> toolTrace;

    private String mode;
    private String model;
    private String provider;
    private Map<String, Number> usage;

    @JsonProperty("session_id")
    private String sessionId;
}
