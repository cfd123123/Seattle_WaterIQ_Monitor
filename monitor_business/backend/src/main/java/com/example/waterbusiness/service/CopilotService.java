package com.example.waterbusiness.service;

import com.example.waterbusiness.client.WaterAiMaintenanceClient;
import com.example.waterbusiness.dto.CopilotChatRequest;
import com.example.waterbusiness.dto.CopilotChatResponse;
import feign.FeignException;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;
import org.springframework.web.server.ResponseStatusException;

@Service
@RequiredArgsConstructor
public class CopilotService {

    private final WaterAiMaintenanceClient waterAiMaintenanceClient;

    public CopilotChatResponse chat(String question, String siteNo) {
        String trimmed = question != null ? question.trim() : "";
        if (!StringUtils.hasText(trimmed)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "question must not be empty");
        }

        CopilotChatRequest req = CopilotChatRequest.builder()
                .question(trimmed)
                .siteNo(StringUtils.hasText(siteNo) ? siteNo.trim() : null)
                .build();

        try {
            return waterAiMaintenanceClient.copilotChat(req);
        } catch (FeignException e) {
            throw mapFeignException(e);
        }
    }

    static ResponseStatusException mapFeignException(FeignException e) {
        int status = e.status();
        if (status == 422) {
            return new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid copilot request.");
        }
        if (status == 503) {
            return new ResponseStatusException(
                    HttpStatus.SERVICE_UNAVAILABLE, friendlyCopilotFailureMessage(503));
        }
        return new ResponseStatusException(HttpStatus.BAD_GATEWAY, friendlyCopilotFailureMessage(502));
    }

    static String friendlyCopilotFailureMessage(int status) {
        if (status == 503) {
            return "AI copilot unavailable (assistant disabled or not configured).";
        }
        return "AI copilot unavailable (LLM request failed).";
    }
}
