package com.example.waterbusiness.dto;

import com.fasterxml.jackson.annotation.JsonAlias;
import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.NotBlank;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class CopilotChatRequest {

    @NotBlank
    private String question;

    /** USGS site number; serialized as site_no when forwarded to ai_service. */
    @JsonProperty("site_no")
    @JsonAlias("siteNo")
    private String siteNo;
}
