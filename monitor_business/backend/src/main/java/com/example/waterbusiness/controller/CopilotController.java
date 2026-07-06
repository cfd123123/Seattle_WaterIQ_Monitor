package com.example.waterbusiness.controller;

import com.example.waterbusiness.dto.ApiResponse;
import com.example.waterbusiness.dto.CopilotChatResponse;
import com.example.waterbusiness.service.CopilotService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.Data;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/copilot")
@RequiredArgsConstructor
@Tag(name = "Ops copilot", description = "RAG copilot over indexed ops documentation (MVP-2)")
public class CopilotController {

    private final CopilotService copilotService;

    @PostMapping("/chat")
    @Operation(summary = "Ask the ops-doc RAG copilot (proxies ai_service POST /copilot/chat)")
    public ApiResponse<CopilotChatResponse> chat(@RequestBody CopilotChatApiRequest body) {
        return ApiResponse.ok(copilotService.chat(body.getQuestion(), body.getSiteNo()));
    }

    @Data
    public static class CopilotChatApiRequest {
        private String question;
        private String siteNo;
    }
}
