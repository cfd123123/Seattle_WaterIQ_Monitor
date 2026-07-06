package com.example.waterbusiness.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import lombok.Data;

import java.util.List;
import java.util.Map;

@Data
@JsonIgnoreProperties(ignoreUnknown = true)
public class CopilotChatResponse {

    private String answer;
    private List<CopilotSourceDto> sources;
    private String model;
    private String provider;
    private Map<String, Object> usage;
}
