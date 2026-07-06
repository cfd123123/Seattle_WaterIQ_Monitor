package com.example.waterbusiness.service;

import com.example.waterbusiness.client.WaterAiMaintenanceClient;
import com.example.waterbusiness.dto.AssistantChatRequest;
import com.example.waterbusiness.dto.AssistantChatResponse;
import com.example.waterbusiness.dto.HistoryMessageDto;
import feign.FeignException;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;
import org.springframework.web.server.ResponseStatusException;

@Service
@RequiredArgsConstructor
public class AssistantService {

    private final WaterAiMaintenanceClient waterAiMaintenanceClient;

    public AssistantChatResponse chat(
            String message,
            String siteNo,
            String sessionId,
            List<HistoryMessageDto> history,
            Integer maxToolRounds) {
        String trimmed = message != null ? message.trim() : "";
        if (!StringUtils.hasText(trimmed)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "message must not be empty");
        }

        AssistantChatRequest req =
                AssistantChatRequest.builder()
                        .message(trimmed)
                        .siteNo(StringUtils.hasText(siteNo) ? siteNo.trim() : null)
                        .sessionId(StringUtils.hasText(sessionId) ? sessionId.trim() : null)
                        .history(history)
                        .maxToolRounds(maxToolRounds)
                        .build();

        try {
            return waterAiMaintenanceClient.assistantChat(req);
        } catch (FeignException e) {
            throw mapFeignException(e);
        }
    }

    static ResponseStatusException mapFeignException(FeignException e) {
        int status = e.status();
        if (status == 422) {
            return new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid assistant agent request.");
        }
        if (status == 503) {
            return new ResponseStatusException(
                    HttpStatus.SERVICE_UNAVAILABLE, friendlyAssistantFailureMessage(503));
        }
        return new ResponseStatusException(HttpStatus.BAD_GATEWAY, friendlyAssistantFailureMessage(502));
    }

    static String friendlyAssistantFailureMessage(int status) {
        if (status == 503) {
            return "AI assistant agent unavailable (assistant disabled or not configured).";
        }
        return "AI assistant agent unavailable (LLM request failed).";
    }
}
