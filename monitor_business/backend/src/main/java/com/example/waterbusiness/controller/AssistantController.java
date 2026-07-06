package com.example.waterbusiness.controller;

import com.example.waterbusiness.dto.ApiResponse;
import com.example.waterbusiness.dto.AssistantChatResponse;
import com.example.waterbusiness.dto.HistoryMessageDto;
import com.example.waterbusiness.service.AssistantService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/assistant")
@RequiredArgsConstructor
@Tag(name = "Assistant agent", description = "L3 NL2API read-only agent (proxies ai_service POST /assistant/chat)")
public class AssistantController {

    private final AssistantService assistantService;

    @PostMapping("/chat")
    @Operation(summary = "Ask the read-only data agent (proxies ai_service POST /assistant/chat)")
    public ApiResponse<AssistantChatResponse> chat(@RequestBody AssistantChatApiRequest body) {
        return ApiResponse.ok(
                assistantService.chat(
                        body.getMessage(),
                        body.getSiteNo(),
                        body.getSessionId(),
                        body.getHistory(),
                        body.getMaxToolRounds()));
    }

    @lombok.Data
    public static class AssistantChatApiRequest {
        private String message;
        private String siteNo;
        private String sessionId;
        private List<HistoryMessageDto> history;
        private Integer maxToolRounds;
    }
}
