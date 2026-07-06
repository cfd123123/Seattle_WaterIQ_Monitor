package com.example.waterbusiness.controller;

import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.example.waterbusiness.dto.AssistantChatResponse;
import com.example.waterbusiness.dto.AssistantSourceDto;
import com.example.waterbusiness.service.AssistantService;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

@WebMvcTest(AssistantController.class)
class AssistantControllerTest {

    @Autowired private MockMvc mockMvc;

    @Autowired private ObjectMapper objectMapper;

    @MockBean private AssistantService assistantService;

    @Test
    void chat_shouldReturn200() throws Exception {
        AssistantSourceDto source = new AssistantSourceDto();
        source.setType("api");
        source.setRef("python:/turbidity/risk-forecast-12h");

        AssistantChatResponse body = new AssistantChatResponse();
        body.setAnswer("recommend_alert is true.");
        body.setSources(List.of(source));
        body.setToolTrace(List.of("get_turbidity_risk_forecast_12h"));
        body.setMode("tools");
        body.setProvider("ollama");

        when(assistantService.chat(
                        eq("What is the 12h turbidity risk for site 12117500?"),
                        eq("12117500"),
                        isNull(),
                        isNull(),
                        isNull()))
                .thenReturn(body);

        mockMvc.perform(
                        post("/api/assistant/chat")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        """
                                        {
                                          "message": "What is the 12h turbidity risk for site 12117500?",
                                          "siteNo": "12117500"
                                        }
                                        """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value("0"))
                .andExpect(jsonPath("$.data.answer").value("recommend_alert is true."))
                .andExpect(jsonPath("$.data.tool_trace[0]")
                        .value("get_turbidity_risk_forecast_12h"));
    }
}
