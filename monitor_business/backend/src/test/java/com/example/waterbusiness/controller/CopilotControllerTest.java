package com.example.waterbusiness.controller;

import com.example.waterbusiness.dto.CopilotChatResponse;
import com.example.waterbusiness.dto.CopilotSourceDto;
import com.example.waterbusiness.service.CopilotService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;
import java.util.Map;

import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(CopilotController.class)
class CopilotControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private CopilotService copilotService;

    @Test
    void chat_shouldReturnOk() throws Exception {
        CopilotSourceDto source = new CopilotSourceDto();
        source.setType("doc");
        source.setRef("docs/turbidity_operations.md#phase-b");
        source.setHeading("Phase B");

        CopilotChatResponse body = new CopilotChatResponse();
        body.setAnswer("Phase B uses persistence-based 12h risk tiers.");
        body.setSources(List.of(source));
        body.setModel("gpt-4o-mini");
        body.setProvider("openai");
        body.setUsage(Map.of("prompt_tokens", 120, "completion_tokens", 40));

        when(copilotService.chat(eq("What is Phase B?"), eq("12117500"))).thenReturn(body);

        mockMvc.perform(
                        post("/api/copilot/chat")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        """
                                        {"question":"What is Phase B?","siteNo":"12117500"}
                                        """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value("0"))
                .andExpect(jsonPath("$.data.answer").value("Phase B uses persistence-based 12h risk tiers."))
                .andExpect(jsonPath("$.data.sources[0].ref").value("docs/turbidity_operations.md#phase-b"))
                .andExpect(jsonPath("$.data.provider").value("openai"));
    }

    @Test
    void chat_shouldReturn503WithFriendlyMessage() throws Exception {
        when(copilotService.chat(eq("hello"), isNull()))
                .thenThrow(new ResponseStatusException(
                        HttpStatus.SERVICE_UNAVAILABLE,
                        "AI copilot unavailable (assistant disabled or not configured)."));

        mockMvc.perform(
                        post("/api/copilot/chat")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"question\":\"hello\"}"))
                .andExpect(status().isServiceUnavailable())
                .andExpect(jsonPath("$.code").value("HTTP_503"))
                .andExpect(jsonPath("$.message")
                        .value("AI copilot unavailable (assistant disabled or not configured)."));
    }

    @Test
    void chat_shouldReturn502WithFriendlyMessage() throws Exception {
        when(copilotService.chat(eq("hello"), isNull()))
                .thenThrow(new ResponseStatusException(
                        HttpStatus.BAD_GATEWAY, "AI copilot unavailable (LLM request failed)."));

        mockMvc.perform(
                        post("/api/copilot/chat")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"question\":\"hello\"}"))
                .andExpect(status().isBadGateway())
                .andExpect(jsonPath("$.code").value("HTTP_502"))
                .andExpect(jsonPath("$.message").value("AI copilot unavailable (LLM request failed)."));
    }
}
