package com.example.waterbusiness.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.Map;
import lombok.Data;

@Data
@JsonIgnoreProperties(ignoreUnknown = true)
public class AssistantToolCallAuditDto {

    private int round;
    private String name;
    private Map<String, Object> arguments;
    private boolean ok;
    private String source;
    private String message;

    @JsonProperty("error_code")
    private String errorCode;

    @JsonProperty("result_preview")
    private Map<String, Object> resultPreview;
}
