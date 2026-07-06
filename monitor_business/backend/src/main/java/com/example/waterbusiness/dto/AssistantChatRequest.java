package com.example.waterbusiness.dto;

import com.fasterxml.jackson.annotation.JsonAlias;
import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import java.util.List;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class AssistantChatRequest {

    @NotBlank
    private String message;

    /** USGS site number; serialized as site_no when forwarded to ai_service. */
    @JsonProperty("site_no")
    @JsonAlias("siteNo")
    private String siteNo;

    @JsonProperty("session_id")
    @JsonAlias("sessionId")
    private String sessionId;

    private List<HistoryMessageDto> history;

    @JsonProperty("max_tool_rounds")
    @JsonAlias("maxToolRounds")
    @Min(1)
    @Max(5)
    private Integer maxToolRounds;
}
